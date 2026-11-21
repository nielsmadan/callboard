targets=()
if [ $# -eq 0 ]; then
    targets=(.)
else
    for f in "$@"; do
        case "$f" in
            CallboardKit/Tests/* | */CallboardKit/Tests/*) ;;
            *) targets+=("$f") ;;
        esac
    done
fi
