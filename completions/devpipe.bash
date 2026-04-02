_devpipe_profiles() {
  local dir
  local profiles=()

  for dir in ".devpipe/profiles" "$HOME/.devpipe/profiles"; do
    [[ -d "$dir" ]] || continue
    while IFS= read -r -d '' profile; do
      profiles+=("$(basename "$profile")")
    done < <(find "$dir" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)
  done

  printf '%s\n' "${profiles[@]}" | sort -u
}

_devpipe_engines() {
  printf '%s\n' auto
  devpipe list-engines 2>/dev/null
}

_devpipe_complete_exec() {
  local cur prev
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"

  case "$prev" in
    --pipe-file)
      COMPREPLY=( $(compgen -f -X '!*.devpipe.yaml' -- "$cur") )
      return
      ;;
    --profile)
      COMPREPLY=( $(compgen -W "$(_devpipe_profiles)" -- "$cur") )
      return
      ;;
    --runner)
      COMPREPLY=( $(compgen -W "$(_devpipe_engines)" -- "$cur") )
      return
      ;;
    --model|--effort)
      COMPREPLY=( $(compgen -W "auto low middle medium high extra" -- "$cur") )
      return
      ;;
  esac

  case "$cur" in
    --pipe-file=*)
      local value="${cur#--pipe-file=}"
      COMPREPLY=( $(compgen -f -X '!*.devpipe.yaml' -- "$value") )
      COMPREPLY=( "${COMPREPLY[@]/#/--pipe-file=}" )
      return
      ;;
    --profile=*)
      local value="${cur#--profile=}"
      COMPREPLY=( $(compgen -W "$(_devpipe_profiles)" -- "$value") )
      COMPREPLY=( "${COMPREPLY[@]/#/--profile=}" )
      return
      ;;
    --runner=*)
      local value="${cur#--runner=}"
      COMPREPLY=( $(compgen -W "$(_devpipe_engines)" -- "$value") )
      COMPREPLY=( "${COMPREPLY[@]/#/--runner=}" )
      return
      ;;
  esac

  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "exec validate doctor install-completion list-engines" -- "$cur") )
    return
  fi

  COMPREPLY=( $(compgen -W \
    "--pipe-file --profile --task --task-id --runner --model --effort --tags --start-agent --stop-agent --topic --with-thinking" \
    -- "$cur") )
}

_devpipe_complete() {
  if [[ ${COMP_WORDS[1]} == "exec" ]]; then
    _devpipe_complete_exec
    return
  fi

  if [[ ${COMP_WORDS[1]} == "install-completion" && $COMP_CWORD -eq 2 ]]; then
    COMPREPLY=( $(compgen -W "zsh bash" -- "${COMP_WORDS[COMP_CWORD]}") )
    return
  fi

  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "exec validate doctor install-completion list-engines" -- "${COMP_WORDS[COMP_CWORD]}") )
    return
  fi

  COMPREPLY=()
}

complete -F _devpipe_complete devpipe
