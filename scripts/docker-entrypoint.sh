#!/usr/bin/env bash
set -euo pipefail

workspace="${LOCAL_SHELL_MCP_WORKSPACE_ROOT:-/workspace}"

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

run_as_root="$(lower "${DOCKER_RUN_AS_ROOT:-false}")"
persist_credentials="$(lower "${DOCKER_PERSISTENT_CREDENTIALS:-true}")"
credentials_dir="${DOCKER_CREDENTIALS_DIR:-/persist/credentials}"
chown_workspace="$(lower "${DOCKER_CHOWN_WORKSPACE:-true}")"
agent_uid="${DOCKER_AGENT_UID:-}"
agent_gid="${DOCKER_AGENT_GID:-}"

is_truthy() {
  case "$1" in
    true|1|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

valid_id() {
  case "$1" in
    ""|*[!0-9]*) return 1 ;;
    *) [ "$1" -gt 0 ] ;;
  esac
}

detect_path_id() {
  local format="$1"
  local path="$2"
  local value
  value="$(stat -c "$format" "$path" 2>/dev/null || true)"
  if valid_id "$value"; then
    printf '%s' "$value"
  fi
}

configure_agent_identity() {
  if [ "$(id -u)" != "0" ]; then
    return 0
  fi

  if [ -z "$agent_uid" ]; then
    agent_uid="$(detect_path_id %u "$workspace")"
  fi
  if [ -z "$agent_gid" ]; then
    agent_gid="$(detect_path_id %g "$workspace")"
  fi
  if [ -z "$agent_uid" ]; then
    agent_uid="1000"
  fi
  if [ -z "$agent_gid" ]; then
    agent_gid="$agent_uid"
  fi

  if ! valid_id "$agent_uid" || ! valid_id "$agent_gid"; then
    echo "Invalid DOCKER_AGENT_UID/DOCKER_AGENT_GID: uid=$agent_uid gid=$agent_gid" >&2
    exit 1
  fi

  if getent group agent >/dev/null 2>&1; then
    groupmod -o -g "$agent_gid" agent
  else
    groupadd -o -g "$agent_gid" agent
  fi

  if id agent >/dev/null 2>&1; then
    usermod -o -u "$agent_uid" -g "$agent_gid" -d /home/agent agent
  else
    useradd -m -o -u "$agent_uid" -g "$agent_gid" -d /home/agent agent
  fi
}

prepare_parent() {
  local path="$1"
  mkdir -p "$(dirname "$path")"
}

link_dir() {
  local source="$1"
  local target="$2"

  prepare_parent "$target"
  mkdir -p "$source"

  if [ -L "$target" ]; then
    local current
    current="$(readlink "$target")"
    if [ "$current" = "$source" ]; then
      return 0
    fi
    rm -f "$target"
  fi

  if [ -e "$target" ]; then
    if [ -d "$target" ]; then
      shopt -s dotglob nullglob
      local entries=("$target"/*)
      if [ "${#entries[@]}" -gt 0 ]; then
        cp -a "${entries[@]}" "$source"/ 2>/dev/null || true
      fi
      rm -rf "$target"
      shopt -u dotglob nullglob
    else
      local backup="${source}.bak.$(date +%s)"
      mv "$target" "$backup"
    fi
  fi

  ln -s "$source" "$target"
}

link_file() {
  local source="$1"
  local target="$2"

  prepare_parent "$target"
  mkdir -p "$(dirname "$source")"

  if [ ! -e "$source" ]; then
    : > "$source"
  fi

  if [ -L "$target" ]; then
    local current
    current="$(readlink "$target")"
    if [ "$current" = "$source" ]; then
      return 0
    fi
    rm -f "$target"
  fi

  if [ -e "$target" ]; then
    if [ -f "$target" ]; then
      if [ ! -e "$source" ]; then
        mv "$target" "$source"
      else
        cat "$target" >> "$source" 2>/dev/null || true
        rm -f "$target"
      fi
    else
      local backup="${source}.bak.$(date +%s)"
      mv "$target" "$backup"
    fi
  fi

  ln -s "$source" "$target"
}

setup_persistent_credentials() {
  local target_user="$1"
  local target_home="$2"

  if ! is_truthy "$persist_credentials"; then
    return 0
  fi

  mkdir -p "$credentials_dir"

  link_dir "$credentials_dir/gh" "$target_home/.config/gh"
  link_file "$credentials_dir/gitconfig" "$target_home/.gitconfig"
  link_file "$credentials_dir/git-credentials" "$target_home/.git-credentials"
  link_dir "$credentials_dir/ssh" "$target_home/.ssh"
  link_file "$credentials_dir/netrc" "$target_home/.netrc"
  link_dir "$credentials_dir/gnupg" "$target_home/.gnupg"

  chmod 700 "$credentials_dir" 2>/dev/null || true
  chmod 700 "$credentials_dir/ssh" "$credentials_dir/gnupg" 2>/dev/null || true
  chmod 600 "$credentials_dir/git-credentials" "$credentials_dir/netrc" 2>/dev/null || true

  if [ "$(id -u)" = "0" ]; then
    chown -R "$target_user:$target_user" "$credentials_dir" "$target_home/.config" "$target_home/.gitconfig" "$target_home/.git-credentials" "$target_home/.ssh" "$target_home/.netrc" "$target_home/.gnupg" 2>/dev/null || true
  fi
}

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$workspace" "$workspace/.local-shell-mcp" "$credentials_dir" /home/agent
  configure_agent_identity
  if is_truthy "$run_as_root"; then
    setup_persistent_credentials root /root
    exec "$@"
  fi
  setup_persistent_credentials agent /home/agent
  if is_truthy "$chown_workspace"; then
    chown -R agent:agent "$workspace" /home/agent "$credentials_dir" 2>/dev/null || true
  fi
  exec runuser -u agent -- "$@"
fi

setup_persistent_credentials "$(id -un)" "${HOME:-/home/agent}"
exec "$@"
