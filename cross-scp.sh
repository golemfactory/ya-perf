#!/usr/local/bin/bash

DEFAULT_SIZE="100M"

NL=$'\n'
NC='\033[0m'
LIGHT_RED='\033[1;31m'
YELLOW='\033[1;33m'
LIGHT_BLUE='\033[1;34m'
LIGHT_GRAY='\033[0;37m'

SCRIPT="$0"

function usage() {
  cat 1>&2 <<EOF
Usage:

    $(basename "${SCRIPT}") -n <nodes> [-s <size>] [-y <path> -y <path2> ..] [-d <path> -d <path2> ..]

Arguments:

    -n | --nodes      node definition JSON file
    -y | --yaml       yaml file(s) containing host definitions
    -d | --dir        directories to scan recursively for yaml files

    -s | --size       file size to transfer (default: ${DEFAULT_SIZE})
EOF
}

function log() {
    printf "[%s] $*" "$(date "+%Y-%m-%d %H:%M:%S")"
}

function info() {
    log "${LIGHT_GRAY}$*${NC}\n"
}

function warn() {
    log "${YELLOW}$*${NC}\n"
}

function error() {
    log "${LIGHT_RED}$*${NC}\n" 1>&2
}

function parse_yaml() {
   local prefix=$2
   local s='[[:space:]]*'
   local w='[a-zA-Z0-9_]*'
   local fs

   fs=$(echo @|tr @ '\034')

   sed -ne "s|^\($s\)\($w\)$s:$s\"\(.*\)\"$s\$|\1$fs\2$fs\3|p" \
        -e "s|^\($s\)\($w\)$s:$s\(.*\)$s\$|\1$fs\2$fs\3|p" "$1" |
   awk -F"$fs" '{
      indent = length($1)/2;
      vname[indent] = $2;
      for (i in vname) {if (i > indent) {delete vname[i]}}
      if (length($3) > 0) {
         vn=""; for (i=0; i<indent; i++) {vn=(vn)(vname[i])("_")}
         printf("%s%s%s=\"%s\"\n", "'"$prefix"'",vn, $2, $3);
      }
   }'
}

function parse_json_kv() {
    local source=$1

    declare -A result=()
    readarray -t items <<<"$(grep -Po '"[^"]*"\s*:.*?"[^"]+"' "${source}")"

    for i in "${items[@]}"; do
        while IFS=":" read -ra REPLY; do
            local id
            local name

            id="${REPLY[0]//\"/}"
            name=$(echo "${REPLY[1]//\"/}" | xargs | cut -d'.' -f1)
            result["${id}"]="${name}"
        done <<< "${i}"
    done

    echo '('
    for key in "${!result[@]}"; do
        echo "[$key]=\"${result[$key]}\""
    done
    echo ')'
}

function escape() {
    local val=$1
    val="${val//\-/_}"
    val="${val//\"/}"
    echo "${val//\./_}"
}

function resolve() {
    set +u
    local prefix=$1

    local var_user="all_hosts_${prefix}_ansible_user"
    local var_host="all_hosts_${prefix}_ansible_host"
    local var_port="all_hosts_${prefix}_ansible_port"

    local user=${!var_user}
    local host=${!var_host}
    local port=${!var_port:-22}

    set -u

    if [[ -z "${user}" || -z "${host}" ]]; then
        echo ""
    else
        echo "${user}@${host}:${port}"    
    fi
}

function transfer() {
    local from=$1
    local to=$2
    local size=$3

    local name
    local src_path
    local dst_path

    local from_host
    local from_port
    local to_host
    local to_port
    local result

    name="scp_transfer_$(date +%s).bin"
    src_path="/tmp/${name}"
    dst_path="/tmp/dl_${name}"

    while IFS=':' read -ra ADDR; do
        from_host="${ADDR[0]}"
        from_port="${ADDR[1]}"
    done <<< "${from}"
    while IFS=':' read -ra ADDR; do
        to_host="${ADDR[0]}"
        to_port="${ADDR[1]}"
    done <<< "${to}"

    echo "${from_host} ${to_host}"

    ssh -p "${from_port}" "${from_host}" "truncate -s ${size} ${src_path}" > /dev/null

    result=$(scp -v -3 "scp://${from}/${src_path}" "scp://${to}/${dst_path}" 2>&1 | grep "Bytes per second" | head -n1)
    result=$(echo "${result}" | awk '{print $NF}' | tail -n1 | sed -E 's/\r//')

    ssh -p "${from_port}" "${from_host}" "rm ${src_path}" > /dev/null
    ssh -p "${to_port}" "${to_host}" "rm ${dst_path}" > /dev/null

    echo "$result"
}

function run() {
    local p_from=$1
    local p_to=$2

    local prefix_from
    local prefix_to
    local from
    local to

    prefix_from=$(escape "${p_from}")
    prefix_to=$(escape "${p_to}")
    from=$(resolve "${prefix_from}" || echo "")
    to=$(resolve "${prefix_to}" || echo "")

    if [[ -z "${from}" ]]; then
        error "host ${p_from} (from) not found"
        exit 1
    fi
    if [[ -z "${to}" ]]; then
        error "host ${p_to} (to) not found"
        exit 1
    fi
    if [[ "${from}" == "${to}" ]]; then
        error "'from' and 'to' are the same host"
        exit 1
    fi

    transfer "${from}" "${to}" "${p_size}"
}

function main() {
    local p_size=${DEFAULT_SIZE}

    declare -a p_nodes=()
    declare -a p_yamls=()
    declare -a p_dirs=()

    declare -A nodes=()
    
    while [[ "$#" -gt 0 ]]; do
        case $1 in
              -h|--help)  usage; exit 0;;
                  -n|--nodes) p_nodes+=("$2"); shift 2;;
            -y|--yaml)  p_yamls+=("$2"); shift 2;;
            -d|--dir)   p_dirs+=("$2"); shift 2;;
            -s|--size)  p_size=$2; shift 2;;
            -- )        shift; break ;;
            * )         usage; exit 1;;
        esac
    done
    shift $((OPTIND -1))

    # read node id to name mapping

    if [[ -z "${p_nodes[*]}" ]]; then
        error "missing JSON node map file"
        exit 1
    fi

    info "${YELLOW}nodes${NC}"

    for n in "${p_nodes[@]}"; do
        declare -A ns="$(parse_json_kv "${n}")"
        for key in "${!ns[@]}"; do
            nodes["${key}"]="${ns[$key]}"
            echo "    ${key}: ${nodes["${key}"]}"
        done
    done

    # read node SSH addresses

    if [[ -n "${p_dirs[*]}" ]]; then
        for d in "${p_dirs[@]}"; do
            while IFS=  read -r -d $'\0'; do
                p_yamls+=("${REPLY[0]}")
            done < <(find "$d" -name "*_hosts.yml" -print0 2>/dev/null)
        done
    fi
    if [[ -z "${p_yamls[*]}" ]]; then
        error "missing YAML node definition file"
        exit 1
    fi
    for y in "${p_yamls[@]}"; do
        eval "$(parse_yaml "${y}" "")"
    done

    # execute transfers

    declare -a results=()

    for k1 in "${!nodes[@]}"; do
        local from=${nodes[$k1]}

        for k2 in "${!nodes[@]}"; do
            local to=${nodes[$k2]}

            if [[ "${from}" == "${to}" ]]; then
                continue
            fi

            log "${YELLOW}running${NC} ${LIGHT_BLUE}${from}${NC} -> ${LIGHT_BLUE}${to}${NC} .. ${NL}"
            speed=$(run "${from}" "${to}")
            echo "    ${speed} B/s"

            results+=("${from}:${to}:${speed}")
        done
    done

    # dump results

    local output
    local last=""
    local json="{"

    for key in "${!results[@]}"; do

        local from=""
        local to=""
        local score=""

        while IFS=':' read -ra ENTRY; do
            from="${ENTRY[0]}"
            to="${ENTRY[1]}"
            score="${ENTRY[2]}"
        done <<< "${results[$key]}"

        if [[ "${last}" == "${from}" ]]; then
            json+=","
            json+="${NL}    \"${to}\": ${score}"
        else
            if [[ "${last}" != "" ]]; then
                json+="${NL}  },"
            fi
            json+="${NL}  \"${from}\": {"
            json+="${NL}    \"${to}\": ${score}"
        fi

        last="${from}"
    done

    if [[ "${last}" != "" ]]; then
          json+="${NL}  }"
    fi
    json+="${NL}}"

    output="output_${p_size}_$(date "+%Y-%m-%d_%H:%M:%S").json"
    echo "${json}" > "${output}"
    info "saved ${YELLOW}${output}${NC}"
    exit 0
}

set -euo pipefail
main "$@"
