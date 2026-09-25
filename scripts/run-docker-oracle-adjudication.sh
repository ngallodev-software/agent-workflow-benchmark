#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="${REPO_ROOT}/scripts/prepare-docker-oracle-adjudication.py"
ROOT="${ADJUDICATION_ROOT:-${REPO_ROOT}/.adjudication/routing-semantic-v1}"
COMPARATIVE_EVAL_REPO="${COMPARATIVE_EVAL_REPO:-${REPO_ROOT}/../agent-workflow-comparative-eval}"
IMAGE="${ADJUDICATION_IMAGE:-agent-workflow-oracle-adjudicator:local}"
CODEX_VERSION="${CODEX_VERSION:-latest}"
DOCKER_NETWORK="${ADJUDICATION_DOCKER_NETWORK:-bridge}"
PYTHON="${PYTHON:-python3}"
ORACLE_VERSION="${ORACLE_VERSION:-routing-semantic-oracle-v1.0.0}"

if [[ -n "${AGENT_WORKFLOW_BIN:-}" ]]; then
    AW="${AGENT_WORKFLOW_BIN}"
elif [[ -n "${AGENT_WORKFLOW_VENV:-}" ]]; then
    AW="${AGENT_WORKFLOW_VENV}/bin/agent-workflow"
else
    AW="$(command -v agent-workflow || true)"
fi

usage() {
    cat <<'EOF'
Usage:
  bash scripts/run-docker-oracle-adjudication.sh prepare-ab
  bash scripts/run-docker-oracle-adjudication.sh build
  bash scripts/run-docker-oracle-adjudication.sh run-ab
  bash scripts/run-docker-oracle-adjudication.sh start-ab
  bash scripts/run-docker-oracle-adjudication.sh compare
  bash scripts/run-docker-oracle-adjudication.sh run-c
  bash scripts/run-docker-oracle-adjudication.sh freeze
  bash scripts/run-docker-oracle-adjudication.sh status

Environment:
  CODEX_CONFIG=/absolute/path/to/minimal/config.toml
  CODEX_ENV_FILE=/absolute/path/to/codex-provider.env
  AGENT_WORKFLOW_VENV=/path/to/shared/venv       # optional
  AGENT_WORKFLOW_BIN=/path/to/agent-workflow     # optional
  COMPARATIVE_EVAL_REPO=/path/to/agent-workflow-comparative-eval
  ADJUDICATION_ROOT=/private/runtime/path
  CODEX_VERSION=latest                           # Docker build argument
  ADJUDICATION_IMAGE=agent-workflow-oracle-adjudicator:local
  ADJUDICATION_DOCKER_NETWORK=bridge
  RESOLUTIONS_FILE=/path/to/resolutions.json     # only for true three-way conflicts
  ADJUDICATION_FORCE=1                           # replace an existing prepared root

Do not put TYPESAFE_API_KEY or any TYPESAFE_* variable in CODEX_ENV_FILE.
EOF
}

die() {
    echo "error: $*" >&2
    exit 1
}

require_tool() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_aw() {
    [[ -n "${AW}" && -x "${AW}" ]] || die "agent-workflow not found; set AGENT_WORKFLOW_VENV or AGENT_WORKFLOW_BIN"
}

require_codex_inputs() {
    [[ -n "${CODEX_CONFIG:-}" ]] || die "CODEX_CONFIG is required"
    [[ -n "${CODEX_ENV_FILE:-}" ]] || die "CODEX_ENV_FILE is required"
    [[ -f "${CODEX_CONFIG}" ]] || die "CODEX_CONFIG does not exist: ${CODEX_CONFIG}"
    [[ -f "${CODEX_ENV_FILE}" ]] || die "CODEX_ENV_FILE does not exist: ${CODEX_ENV_FILE}"

    if grep -Eq '^[[:space:]]*(export[[:space:]]+)?TYPESAFE_[A-Za-z0-9_]*[[:space:]]*=' "${CODEX_ENV_FILE}"; then
        die "CODEX_ENV_FILE contains TYPESAFE_* credentials; blinded adjudicators must not receive them"
    fi

    "${PYTHON}" "${HELPER}" validate-codex-config --config "${CODEX_CONFIG}" >/dev/null
}

build_image() {
    require_tool docker
    docker info >/dev/null 2>&1 || die "Docker daemon is not reachable"

    local args=(
        build
        --pull
        --build-arg "CODEX_VERSION=${CODEX_VERSION}"
        -f "${REPO_ROOT}/docker/adjudication/Dockerfile"
        -t "${IMAGE}"
        "${REPO_ROOT}"
    )
    if [[ "${CODEX_VERSION}" == "latest" || "${ADJUDICATION_NO_CACHE:-0}" == "1" ]]; then
        args=(build --pull --no-cache --build-arg "CODEX_VERSION=${CODEX_VERSION}" -f "${REPO_ROOT}/docker/adjudication/Dockerfile" -t "${IMAGE}" "${REPO_ROOT}")
    fi
    docker "${args[@]}"

    local codex_version
    codex_version="$(docker run --rm --entrypoint codex "${IMAGE}" --version)"
    if [[ -d "${ROOT}/coordinator" ]]; then
        docker image inspect "${IMAGE}" --format '{{.Id}}' > "${ROOT}/coordinator/docker-image-id.txt"
        printf '%s\n' "${codex_version}" > "${ROOT}/coordinator/codex-version.txt"
    fi
    echo "built ${IMAGE}: ${codex_version}"
}

ensure_image() {
    require_tool docker
    if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
        build_image
    fi
}

run_agent() {
    local slot="$1"
    local adjudicator_id="$2"
    local input_dir="${ROOT}/${slot}/input"
    local output_dir="${ROOT}/${slot}/output"

    [[ -d "${input_dir}" ]] || die "missing prepared input directory: ${input_dir}"
    [[ -d "${output_dir}" ]] || die "missing prepared output directory: ${output_dir}"
    if [[ -e "${output_dir}/adjudication.json" && "${ADJUDICATION_RERUN:-0}" != "1" ]]; then
        die "${slot} already has adjudication.json; set ADJUDICATION_RERUN=1 only if you intentionally want a new independent pass"
    fi
    if [[ "${ADJUDICATION_RERUN:-0}" == "1" ]]; then
        rm -f "${output_dir}"/*
    fi

    local expected_sha
    expected_sha="$(sha256sum "${input_dir}/oracle-view.json" | awk '{print $1}')"
    local config_abs env_abs input_abs output_abs
    config_abs="$(readlink -f "${CODEX_CONFIG}")"
    env_abs="$(readlink -f "${CODEX_ENV_FILE}")"
    input_abs="$(readlink -f "${input_dir}")"
    output_abs="$(readlink -f "${output_dir}")"

    docker run --rm \
        --name "aw-oracle-${slot}-$$" \
        --hostname "oracle-${slot}" \
        --read-only \
        --cap-drop=ALL \
        --security-opt=no-new-privileges:true \
        --pids-limit=256 \
        --user "$(id -u):$(id -g)" \
        --tmpfs /tmp:rw,nosuid,nodev,size=512m,mode=1777 \
        --network "${DOCKER_NETWORK}" \
        --env-file "${env_abs}" \
        -e "HOME=/tmp/home" \
        -e "CODEX_HOME=/tmp/codex-home" \
        -e "ADJUDICATOR_ID=${adjudicator_id}" \
        -e "EXPECTED_VIEW_SHA256=${expected_sha}" \
        -v "${config_abs}:/run/adjudication/config.toml:ro" \
        -v "${input_abs}:/input:ro" \
        -v "${output_abs}:/output:rw" \
        "${IMAGE}"
}

prepare_ab() {
    require_tool "${PYTHON}"
    local force=()
    if [[ "${ADJUDICATION_FORCE:-0}" == "1" ]]; then
        force=(--force)
    fi
    "${PYTHON}" "${HELPER}" prepare-ab \
        --root "${ROOT}" \
        --comparative-eval-repo "${COMPARATIVE_EVAL_REPO}" \
        "${force[@]}"
}

run_ab() {
    require_codex_inputs
    require_aw
    ensure_image

    echo "starting independent adjudicators A and B in separate containers"
    set +e
    run_agent a codex-a >"${ROOT}/a/container.log" 2>&1 &
    local pid_a=$!
    run_agent b codex-b >"${ROOT}/b/container.log" 2>&1 &
    local pid_b=$!

    wait "${pid_a}"
    local status_a=$?
    wait "${pid_b}"
    local status_b=$?
    set -e

    if [[ "${status_a}" -ne 0 || "${status_b}" -ne 0 ]]; then
        echo "A exit: ${status_a}; B exit: ${status_b}" >&2
        echo "inspect ${ROOT}/a/container.log and ${ROOT}/b/container.log" >&2
        exit 1
    fi

    "${AW}" benchmark decision-study-adjudication-validate \
        "${ROOT}/coordinator/oracle-authoring-view.json" \
        "${ROOT}/a/output/adjudication.json" \
        > "${ROOT}/coordinator/validation-a.json"
    "${AW}" benchmark decision-study-adjudication-validate \
        "${ROOT}/coordinator/oracle-authoring-view.json" \
        "${ROOT}/b/output/adjudication.json" \
        > "${ROOT}/coordinator/validation-b.json"

    echo "A/B completed and validated independently."
}

compare_ab() {
    require_aw
    [[ -f "${ROOT}/a/output/adjudication.json" ]] || die "A adjudication is missing"
    [[ -f "${ROOT}/b/output/adjudication.json" ]] || die "B adjudication is missing"

    local dispute="${ROOT}/coordinator/oracle-disputes-for-c.json"
    [[ ! -e "${dispute}" ]] || die "dispute view already exists: ${dispute}"

    "${AW}" benchmark decision-study-oracle-disputes \
        "${ROOT}/coordinator/oracle-authoring-view.json" \
        "${ROOT}/a/output/adjudication.json" \
        "${ROOT}/b/output/adjudication.json" \
        "${dispute}" \
        > "${ROOT}/coordinator/dispute-summary.json"

    "${PYTHON}" "${HELPER}" prepare-c \
        --root "${ROOT}" \
        --dispute-view "${dispute}" \
        > "${ROOT}/coordinator/c-preparation.json"

    local count
    count="$("${PYTHON}" -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["cases"]))' "${dispute}")"
    if [[ "${count}" == "0" ]]; then
        echo "A/B have no disagreements; adjudicator C is not required."
    else
        echo "prepared blinded C handoff for ${count} disputed cases."
    fi
}

run_c() {
    require_codex_inputs
    require_aw
    ensure_image

    local dispute="${ROOT}/coordinator/oracle-disputes-for-c.json"
    [[ -f "${dispute}" ]] || die "run compare before run-c"

    local count
    count="$("${PYTHON}" -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["cases"]))' "${dispute}")"
    if [[ "${count}" == "0" ]]; then
        echo "C is not required; A/B have no disagreements."
        return 0
    fi

    run_agent c codex-c >"${ROOT}/c/container.log" 2>&1
    "${AW}" benchmark decision-study-adjudication-validate \
        "${dispute}" \
        "${ROOT}/c/output/adjudication.json" \
        > "${ROOT}/coordinator/validation-c.json"
    echo "C completed and validated against the blinded dispute-only view."
}

freeze_oracle() {
    require_aw
    local view="${ROOT}/coordinator/oracle-authoring-view.json"
    local corpus="${ROOT}/coordinator/routing-corpus.json"
    local a="${ROOT}/a/output/adjudication.json"
    local b="${ROOT}/b/output/adjudication.json"
    local oracle="${ROOT}/coordinator/oracle.json"
    local dispute="${ROOT}/coordinator/oracle-disputes-for-c.json"

    for required in "${view}" "${corpus}" "${a}" "${b}"; do
        [[ -f "${required}" ]] || die "required freeze input missing: ${required}"
    done
    [[ ! -e "${oracle}" ]] || die "oracle is already frozen at ${oracle}"

    local args=(
        benchmark decision-study-oracle-freeze
        "${view}" "${a}" "${b}" "${oracle}"
        --oracle-version "${ORACLE_VERSION}"
    )

    if [[ -f "${dispute}" ]]; then
        local count
        count="$("${PYTHON}" -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["cases"]))' "${dispute}")"
        if [[ "${count}" != "0" ]]; then
            [[ -f "${ROOT}/c/output/adjudication.json" ]] || die "C adjudication is required before freeze"
            args+=(--c-view "${dispute}" --c-pass "${ROOT}/c/output/adjudication.json")
        fi
    fi

    if [[ -n "${RESOLUTIONS_FILE:-}" ]]; then
        [[ -f "${RESOLUTIONS_FILE}" ]] || die "RESOLUTIONS_FILE does not exist: ${RESOLUTIONS_FILE}"
        args+=(--resolutions "${RESOLUTIONS_FILE}")
    fi

    "${AW}" "${args[@]}" > "${ROOT}/coordinator/freeze-result.json"
    "${AW}" benchmark decision-study-validate "${corpus}" --oracle "${oracle}" \
        > "${ROOT}/coordinator/final-validation.json"

    echo "frozen oracle: ${oracle}"
    echo "freeze manifest: ${oracle}.manifest.json"
}

status() {
    echo "root: ${ROOT}"
    for slot in a b c; do
        if [[ -f "${ROOT}/${slot}/output/adjudication.json" ]]; then
            echo "${slot}: adjudication complete"
        elif [[ -d "${ROOT}/${slot}/input" ]]; then
            echo "${slot}: prepared"
        else
            echo "${slot}: not prepared"
        fi
    done
    if [[ -f "${ROOT}/coordinator/oracle-disputes-for-c.json" ]]; then
        echo "A/B comparison: complete"
    else
        echo "A/B comparison: not run"
    fi
    if [[ -f "${ROOT}/coordinator/oracle.json" ]]; then
        echo "oracle: FROZEN"
        sha256sum "${ROOT}/coordinator/oracle.json"
    else
        echo "oracle: not frozen"
    fi
}

command="${1:-}"
case "${command}" in
    prepare-ab)
        prepare_ab
        ;;
    build)
        build_image
        ;;
    run-ab)
        run_ab
        ;;
    start-ab)
        prepare_ab
        build_image
        run_ab
        ;;
    compare)
        compare_ab
        ;;
    run-c)
        run_c
        ;;
    freeze)
        freeze_oracle
        ;;
    status)
        status
        ;;
    -h|--help|help|"")
        usage
        ;;
    *)
        usage >&2
        die "unknown command: ${command}"
        ;;
esac
