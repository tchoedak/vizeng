#!/usr/bin/env bash
# Install (or refresh) vizeng from this checkout into every Claude Code and Codex config dir:
# ~/.claude, ~/.codex and any ~/.claude-* / ~/.codex-* profile dirs that exist.
# Override with CLAUDE_DIRS / CODEX_DIRS (space-separated).
# Both harnesses cache installed plugins by version, so after editing the skill bump the
# version in both plugin.json files and re-run this.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
shopt -s nullglob
read -r -a CLAUDE <<< "${CLAUDE_DIRS:-$(echo "$HOME"/.claude "$HOME"/.claude-*)}"
read -r -a CODEX <<< "${CODEX_DIRS:-$(echo "$HOME"/.codex "$HOME"/.codex-*)}"

if command -v claude >/dev/null; then
  for d in "${CLAUDE[@]}"; do
    # profile dirs must look like a Claude config (other tools also use ~/.claude-*)
    [ "$d" = "$HOME/.claude" ] && [ -d "$d" ] || [ -e "$d/settings.json" ] || [ -d "$d/projects" ] || continue
    echo "== claude $d"
    CLAUDE_CONFIG_DIR="$d" claude plugin marketplace add "$ROOT" 2>/dev/null \
      || CLAUDE_CONFIG_DIR="$d" claude plugin marketplace update vizeng
    CLAUDE_CONFIG_DIR="$d" claude plugin install vizeng@vizeng 2>/dev/null \
      || CLAUDE_CONFIG_DIR="$d" claude plugin update vizeng@vizeng
  done
fi

if command -v codex >/dev/null; then
  for d in "${CODEX[@]}"; do
    [ "$d" = "$HOME/.codex" ] && [ -d "$d" ] || [ -e "$d/config.toml" ] || continue
    echo "== codex $d"
    CODEX_HOME="$d" codex plugin marketplace add "$ROOT" || true
    CODEX_HOME="$d" codex plugin add vizeng@vizeng
  done
fi
echo "done"
