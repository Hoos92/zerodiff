"""The built-in minimal coding agent (`--llm provider:model`).

Retrace still ships no model: this is a thin, least-privilege API client
for the LLM the user chooses and pays for. By design it is NOT a general
agent -- no shell, no tools, no file access beyond an explicit allowlist,
no network beyond the single LLM call per iteration. It receives the
loop's fix prompt plus the current rewrite files, and may only reply with
full replacement contents for those same files. Everything it writes is
then judged by replay and the quality gate, like any other agent's work.

Providers: `anthropic`, `openai`, and `openai-compatible` (any endpoint
speaking the OpenAI chat wire format: Ollama, vLLM, OpenRouter, Gemini's
compatibility endpoint) -- all via stdlib urllib, zero dependencies.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_MAX_TOKENS = 8000
FILE_BLOCK_RE = re.compile(
    r"<<<RETRACE-FILE:\s*(.+?)>>>\r?\n(.*?)<<<RETRACE-END>>>", re.DOTALL)

SYSTEM_PROMPT = """\
You are the fix agent inside Retrace, a behavioral verification harness.
You receive a report of divergences between recorded original behavior
and a rewrite, plus the current contents of the rewrite source files.

Rules:
- Behavior must match the original exactly (exception types, messages,
  value types, in-place argument mutations) even where it looks wrong.
- Never use eval/exec, os.system, subprocess with shell=True, pickle
  loading, string-built SQL, or hardcoded secrets; never disable TLS
  verification; no mutable default arguments; keep functions small.
- Reply ONLY with full replacement contents for the files you change,
  in this exact format (one block per file, nothing else matters):

<<<RETRACE-FILE: filename.py>>>
...entire new file contents...
<<<RETRACE-END>>>
"""

_DEFAULT_BASE_URLS = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
}
_DEFAULT_KEY_ENVS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}
PROVIDERS = ("anthropic", "openai", "openai-compatible")


class AgentError(Exception):
    pass


def parse_llm_spec(spec):
    provider, sep, model = spec.partition(":")
    if not sep or not model or provider not in PROVIDERS:
        raise AgentError(
            "invalid --llm spec %r; expected provider:model with provider "
            "one of %s" % (spec, ", ".join(PROVIDERS)))
    return provider, model


class BuiltinAgent:
    def __init__(self, spec, base_url=None, max_tokens=DEFAULT_MAX_TOKENS,
                 timeout=1800.0, api_key_env=None):
        self.provider, self.model = parse_llm_spec(spec)
        if self.provider == "openai-compatible" and not base_url:
            raise AgentError("--llm openai-compatible requires "
                             "--llm-base-url (e.g. your Ollama/OpenRouter "
                             "endpoint)")
        self.base_url = (base_url or
                         _DEFAULT_BASE_URLS[self.provider]).rstrip("/")
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.api_key_env = api_key_env

    # -- key handling --------------------------------------------------------
    def _api_key(self):
        candidates = []
        if self.api_key_env:
            candidates.append(self.api_key_env)
        elif self.provider == "openai-compatible":
            candidates += ["RETRACE_LLM_API_KEY", "OPENAI_API_KEY"]
        else:
            candidates.append(_DEFAULT_KEY_ENVS[self.provider])
        for env in candidates:
            value = os.environ.get(env)
            if value:
                return value
        if self.provider == "openai-compatible":
            return "not-needed"  # local endpoints (Ollama) ignore the key
        raise AgentError(
            "no API key: set %s (or [agent] api_key_env in retrace.toml)"
            % " or ".join(candidates))

    # -- wire formats ---------------------------------------------------------
    def _build_request(self, system, user):
        if self.provider == "anthropic":
            url = self.base_url + "/v1/messages"
            headers = {"x-api-key": self._api_key(),
                       "anthropic-version": "2023-06-01",
                       "content-type": "application/json"}
            body = {"model": self.model, "max_tokens": self.max_tokens,
                    "temperature": 0, "system": system,
                    "messages": [{"role": "user", "content": user}]}
        else:
            url = self.base_url + "/chat/completions"
            headers = {"Authorization": "Bearer " + self._api_key(),
                       "content-type": "application/json"}
            body = {"model": self.model, "max_tokens": self.max_tokens,
                    "temperature": 0,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}]}
        return url, headers, body

    def _parse_response(self, data):
        if self.provider == "anthropic":
            text = "".join(part.get("text", "")
                           for part in data.get("content", []))
            stopped_short = data.get("stop_reason") == "max_tokens"
        else:
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
            stopped_short = choice.get("finish_reason") == "length"
        if stopped_short:
            raise AgentError(
                "LLM response was truncated at %d tokens; raise "
                "[agent] max_tokens in retrace.toml" % self.max_tokens)
        return text

    def _request(self, system, user):
        url, headers, body = self._build_request(system, user)
        payload = json.dumps(body).encode("utf-8")
        last_error = None
        for attempt in (1, 2):
            request = urllib.request.Request(url, data=payload,
                                             headers=headers)
            try:
                with urllib.request.urlopen(request,
                                            timeout=self.timeout) as resp:
                    return self._parse_response(
                        json.loads(resp.read().decode("utf-8")))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                if exc.code in (401, 403):
                    raise AgentError(
                        "LLM API rejected the key (HTTP %d): check your "
                        "API key. %s" % (exc.code, detail))
                if exc.code == 404:
                    raise AgentError(
                        "model or endpoint not found (HTTP 404): check "
                        "the model name %r. %s" % (self.model, detail))
                last_error = AgentError("LLM API error HTTP %d: %s"
                                        % (exc.code, detail))
                if exc.code not in (429, 500, 502, 503, 529):
                    raise last_error
            except (urllib.error.URLError, OSError) as exc:
                last_error = AgentError(
                    "cannot reach LLM endpoint %s: %s" % (url, exc))
            if attempt == 1:
                time.sleep(2)
        raise last_error

    # -- the fix step ---------------------------------------------------------
    def run(self, prompt, files, workdir):
        """AgentRunner contract: 0 = agent acted, nonzero = it failed."""
        sections = [prompt, "\nCurrent contents of the rewrite files:\n"]
        display_names = {}
        for path in files:
            name = os.path.relpath(path, workdir)
            display_names[os.path.normcase(os.path.abspath(path))] = name
            with open(path, "r", encoding="utf-8") as f:
                sections.append("<<<RETRACE-FILE: %s>>>\n%s<<<RETRACE-END>>>"
                                % (name, f.read()))
        try:
            reply = self._request(SYSTEM_PROMPT, "\n".join(sections))
        except AgentError as exc:
            print("retrace agent: %s" % exc)
            return 1

        blocks = FILE_BLOCK_RE.findall(reply)
        if not blocks:
            print("retrace agent: reply contained no RETRACE-FILE blocks; "
                  "nothing written")
            return 1
        allowed = {os.path.normcase(os.path.abspath(p)) for p in files}
        wrote = 0
        for name, content in blocks:
            name = name.strip()
            if os.path.isabs(name):
                print("retrace agent: rejected absolute path %r" % name)
                continue
            target = os.path.normcase(
                os.path.abspath(os.path.join(workdir, name)))
            if target not in allowed:
                print("retrace agent: rejected write outside the rewrite "
                      "allowlist: %r" % name)
                continue
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(content if content.endswith("\n")
                        else content + "\n")
            wrote += 1
        if wrote == 0:
            print("retrace agent: no allowed files were written")
            return 1
        print("retrace agent: wrote %d file(s) via %s:%s"
              % (wrote, self.provider, self.model))
        return 0

    def check(self):
        """One tiny round-trip to validate key/model/endpoint."""
        reply = self._request("You are a connectivity check.",
                              "Reply with exactly: OK")
        return reply.strip()[:40]
