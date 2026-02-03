#!/bin/bash
#
# Clawedbot/Openbot Installation Script
#
# Safe, auditable installer for OpenBot runtime on EC2.
# Requires explicit --yes flag for any mutating operations.
#
# Fixed paths:
#   repo:        /opt/openbot
#   venv:        /var/lib/openbot/venv
#   config:      /etc/openbot/config.yaml
#   credentials: /etc/openbot/credentials.yaml
#   data:        /var/lib/openbot/{logs,receipts,workdir}
#   wrapper:     /usr/local/bin/openbot
#
# Usage:
#   ./clawedbot-install.sh --help
#   ./clawedbot-install.sh --print-plan
#   sudo ./clawedbot-install.sh --yes
#
# Repository: https://github.com/launchplugai/openbot
#

set -euo pipefail

# =============================================================================
# CONSTANTS
# =============================================================================

readonly VERSION="1.0.0"
readonly SCRIPT_NAME="$(basename "$0")"

# Fixed paths (do not change)
readonly REPO_DIR="/opt/openbot"
readonly VENV_DIR="/var/lib/openbot/venv"
readonly DATA_DIR="/var/lib/openbot"
readonly CONFIG_DIR="/etc/openbot"
readonly WRAPPER_PATH="/usr/local/bin/openbot"
readonly WRAPPER_RUN_PATH="/usr/local/bin/openbot-run"
readonly OPENBOT_USER="openbot"
readonly OPENBOT_GROUP="openbot"

# Data subdirectories
readonly DATA_SUBDIRS=("logs" "receipts" "workdir")

# Expected wrapper content (canonical)
readonly EXPECTED_WRAPPER='#!/bin/bash
exec /var/lib/openbot/venv/bin/python -m openbot.cli "$@"'

# =============================================================================
# GLOBALS (set by parse_args)
# =============================================================================

FLAG_YES=false
FLAG_PRINT_PLAN=false
FLAG_NO_PULL=false
FLAG_DOCTOR_ONLY=false
FLAG_ENABLE_SERVICES=false
CONFIG_PATH="/etc/openbot/config.yaml"
CREDENTIALS_PATH="/etc/openbot/credentials.yaml"

# Tracking
CHECKS_PASSED=0
CHECKS_FAILED=0
ACTIONS_PLANNED=()

# =============================================================================
# LOGGING
# =============================================================================

log_info() {
    echo "[INFO] $*"
}

log_warn() {
    echo "[WARN] $*" >&2
}

log_error() {
    echo "[ERROR] $*" >&2
}

log_ok() {
    echo "[OK]   $*"
    ((CHECKS_PASSED++)) || true
}

log_fail() {
    echo "[FAIL] $*"
    ((CHECKS_FAILED++)) || true
}

log_action() {
    ACTIONS_PLANNED+=("$*")
    echo "[PLAN] $*"
}

# =============================================================================
# USAGE
# =============================================================================

usage() {
    cat <<EOF
Clawedbot/Openbot Installer v${VERSION}

USAGE:
    $SCRIPT_NAME [OPTIONS]

OPTIONS:
    --help              Show this help message
    --print-plan        Print planned actions and exit (no changes)
    --yes               Execute mutating steps (REQUIRED for changes)
    --no-pull           Skip git fetch/pull
    --doctor-only       Only run doctor check, no installs
    --enable-services   Enable and start systemd services (requires --yes)
    --config PATH       Config file path (default: /etc/openbot/config.yaml)
    --credentials PATH  Credentials file path (default: /etc/openbot/credentials.yaml)

EXAMPLES:
    # Check current state (read-only)
    $SCRIPT_NAME --print-plan

    # Full install with mutating steps
    sudo $SCRIPT_NAME --yes

    # Install without git pull
    sudo $SCRIPT_NAME --yes --no-pull

    # Just run doctor
    sudo $SCRIPT_NAME --doctor-only

    # Full install and enable services
    sudo $SCRIPT_NAME --yes --enable-services

FIXED PATHS:
    Repo:        $REPO_DIR
    Venv:        $VENV_DIR
    Config:      $CONFIG_DIR/config.yaml
    Credentials: $CONFIG_DIR/credentials.yaml
    Data:        $DATA_DIR/{logs,receipts,workdir}
    Wrapper:     $WRAPPER_PATH

EOF
    exit 0
}

# =============================================================================
# ARGUMENT PARSING
# =============================================================================

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --help|-h)
                usage
                ;;
            --print-plan)
                FLAG_PRINT_PLAN=true
                shift
                ;;
            --yes|-y)
                FLAG_YES=true
                shift
                ;;
            --no-pull)
                FLAG_NO_PULL=true
                shift
                ;;
            --doctor-only)
                FLAG_DOCTOR_ONLY=true
                shift
                ;;
            --enable-services)
                FLAG_ENABLE_SERVICES=true
                shift
                ;;
            --config)
                CONFIG_PATH="$2"
                shift 2
                ;;
            --credentials)
                CREDENTIALS_PATH="$2"
                shift 2
                ;;
            *)
                log_error "Unknown option: $1"
                echo "Use --help for usage information."
                exit 1
                ;;
        esac
    done
}

# =============================================================================
# PREFLIGHT CHECKS
# =============================================================================

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_fail "Not running as root (use sudo for mutating operations)"
        return 1
    else
        log_ok "Running as root"
        return 0
    fi
}

check_repo_exists() {
    if [[ -d "$REPO_DIR" && -d "$REPO_DIR/.git" ]]; then
        log_ok "Repo exists: $REPO_DIR"
        return 0
    else
        log_fail "Repo missing or not a git repo: $REPO_DIR"
        log_action "Clone repo to $REPO_DIR (manual step)"
        return 1
    fi
}

check_data_dir_exists() {
    if [[ -d "$DATA_DIR" ]]; then
        log_ok "Data dir exists: $DATA_DIR"
        return 0
    else
        log_fail "Data dir missing: $DATA_DIR"
        log_action "Create directory: $DATA_DIR"
        return 1
    fi
}

check_data_subdirs() {
    local all_exist=true
    for subdir in "${DATA_SUBDIRS[@]}"; do
        local path="$DATA_DIR/$subdir"
        if [[ -d "$path" ]]; then
            log_ok "Data subdir exists: $path"
        else
            log_fail "Data subdir missing: $path"
            log_action "Create directory: $path"
            all_exist=false
        fi
    done
    $all_exist
}

check_venv_exists() {
    if [[ -d "$VENV_DIR" && -x "$VENV_DIR/bin/python" ]]; then
        log_ok "Venv exists with python: $VENV_DIR"
        return 0
    elif [[ -d "$VENV_DIR" ]]; then
        log_fail "Venv exists but python missing: $VENV_DIR"
        log_action "Recreate venv at $VENV_DIR"
        return 1
    else
        log_fail "Venv missing: $VENV_DIR"
        log_action "Create venv at $VENV_DIR"
        return 1
    fi
}

check_wrapper() {
    if [[ ! -f "$WRAPPER_PATH" ]]; then
        log_fail "Wrapper missing: $WRAPPER_PATH"
        log_action "Create wrapper: $WRAPPER_PATH"
        return 1
    fi

    local current_content
    current_content=$(cat "$WRAPPER_PATH")
    if [[ "$current_content" == "$EXPECTED_WRAPPER" ]]; then
        log_ok "Wrapper content correct: $WRAPPER_PATH"
        return 0
    else
        log_fail "Wrapper content incorrect: $WRAPPER_PATH"
        log_action "Fix wrapper: $WRAPPER_PATH"
        return 1
    fi
}

check_config_dir() {
    if [[ -d "$CONFIG_DIR" ]]; then
        log_ok "Config dir exists: $CONFIG_DIR"
        return 0
    else
        log_fail "Config dir missing: $CONFIG_DIR"
        log_action "Create directory: $CONFIG_DIR"
        return 1
    fi
}

check_config_file() {
    if [[ -f "$CONFIG_PATH" ]]; then
        log_ok "Config file exists: $CONFIG_PATH"
        return 0
    else
        log_fail "Config file missing: $CONFIG_PATH"
        log_action "Copy template to: $CONFIG_PATH"
        return 1
    fi
}

check_credentials_file() {
    if [[ -f "$CREDENTIALS_PATH" ]]; then
        log_ok "Credentials file exists: $CREDENTIALS_PATH"
        return 0
    else
        log_warn "Credentials file missing: $CREDENTIALS_PATH (user must create)"
        return 0  # Not a failure, just a warning
    fi
}

check_openbot_user() {
    if id "$OPENBOT_USER" &>/dev/null; then
        log_ok "User exists: $OPENBOT_USER"
        return 0
    else
        log_fail "User missing: $OPENBOT_USER"
        log_action "Create user: $OPENBOT_USER"
        return 1
    fi
}

check_openbot_installed() {
    if [[ -x "$VENV_DIR/bin/pip" ]]; then
        if "$VENV_DIR/bin/pip" show openbot &>/dev/null; then
            log_ok "Openbot package installed in venv"
            return 0
        else
            log_fail "Openbot package not installed in venv"
            log_action "Install: pip install -e $REPO_DIR"
            return 1
        fi
    else
        log_fail "Cannot check openbot package (venv pip missing)"
        return 1
    fi
}

run_preflight_checks() {
    echo ""
    echo "=== Preflight Checks ==="
    echo ""

    # These checks always run
    check_repo_exists || true
    check_data_dir_exists || true
    check_data_subdirs || true
    check_venv_exists || true
    check_wrapper || true
    check_config_dir || true
    check_config_file || true
    check_credentials_file || true
    check_openbot_user || true

    # Only check if venv exists
    if [[ -x "$VENV_DIR/bin/pip" ]]; then
        check_openbot_installed || true
    fi

    # Root check (for mutating operations)
    if $FLAG_YES; then
        check_root || true
    fi

    echo ""
    echo "=== Preflight Summary ==="
    echo "Checks passed: $CHECKS_PASSED"
    echo "Checks failed: $CHECKS_FAILED"
    echo ""
}

# =============================================================================
# MUTATING OPERATIONS
# =============================================================================

create_user_if_missing() {
    if ! id "$OPENBOT_USER" &>/dev/null; then
        log_info "Creating user: $OPENBOT_USER"
        useradd --system --shell /bin/false --home-dir "$DATA_DIR" "$OPENBOT_USER"
        log_ok "Created user: $OPENBOT_USER"
    fi
}

create_directories() {
    log_info "Ensuring directories exist..."

    # Data dir
    if [[ ! -d "$DATA_DIR" ]]; then
        mkdir -p "$DATA_DIR"
        log_ok "Created: $DATA_DIR"
    fi

    # Data subdirs
    for subdir in "${DATA_SUBDIRS[@]}"; do
        local path="$DATA_DIR/$subdir"
        if [[ ! -d "$path" ]]; then
            mkdir -p "$path"
            log_ok "Created: $path"
        fi
    done

    # Config dir
    if [[ ! -d "$CONFIG_DIR" ]]; then
        mkdir -p "$CONFIG_DIR"
        log_ok "Created: $CONFIG_DIR"
    fi

    # Set ownership
    chown -R "$OPENBOT_USER:$OPENBOT_GROUP" "$DATA_DIR"
    chmod 750 "$DATA_DIR"
    chown root:"$OPENBOT_GROUP" "$CONFIG_DIR"
    chmod 750 "$CONFIG_DIR"

    log_ok "Directory ownership set"
}

create_venv() {
    if [[ ! -d "$VENV_DIR" ]] || [[ ! -x "$VENV_DIR/bin/python" ]]; then
        log_info "Creating virtual environment: $VENV_DIR"

        # Ensure python3-venv is available
        if ! python3 -m venv --help &>/dev/null; then
            log_info "Installing python3-venv..."
            apt-get update -qq
            apt-get install -y -qq python3-venv
        fi

        # Create venv
        python3 -m venv "$VENV_DIR"
        chown -R "$OPENBOT_USER:$OPENBOT_GROUP" "$VENV_DIR"
        log_ok "Created venv: $VENV_DIR"
    fi
}

git_pull() {
    if $FLAG_NO_PULL; then
        log_info "Skipping git pull (--no-pull)"
        return 0
    fi

    log_info "Pulling latest from origin..."
    cd "$REPO_DIR"

    # Fetch first
    git fetch origin 2>&1 || {
        log_warn "git fetch failed, continuing..."
        return 0
    }

    # Get current branch
    local branch
    branch=$(git rev-parse --abbrev-ref HEAD)

    # Try fast-forward pull
    if git pull --ff-only origin "$branch" 2>&1; then
        log_ok "Git pull successful"
    else
        log_warn "Git pull failed (non-fast-forward?), continuing with current state"
    fi
}

install_openbot_package() {
    log_info "Installing openbot package (editable)..."

    # Upgrade pip first
    "$VENV_DIR/bin/pip" install --upgrade pip -q

    # Install editable
    "$VENV_DIR/bin/pip" install -e "$REPO_DIR" -q

    log_ok "Installed openbot package"
}

write_wrapper() {
    local current_content=""
    if [[ -f "$WRAPPER_PATH" ]]; then
        current_content=$(cat "$WRAPPER_PATH")
    fi

    if [[ "$current_content" != "$EXPECTED_WRAPPER" ]]; then
        # Backup if exists
        if [[ -f "$WRAPPER_PATH" ]]; then
            local backup="${WRAPPER_PATH}.bak.$(date +%Y%m%d_%H%M%S)"
            cp -a "$WRAPPER_PATH" "$backup"
            log_info "Backed up old wrapper to: $backup"
        fi

        # Write atomically
        local tmpfile
        tmpfile=$(mktemp)
        echo "$EXPECTED_WRAPPER" > "$tmpfile"
        mv "$tmpfile" "$WRAPPER_PATH"
        chmod 755 "$WRAPPER_PATH"
        chown root:root "$WRAPPER_PATH"

        log_ok "Wrote wrapper: $WRAPPER_PATH"
    else
        log_info "Wrapper already correct, skipping"
    fi
}

copy_wrapper_run() {
    local src="$REPO_DIR/scripts/openbot-run"
    if [[ -f "$src" ]]; then
        cp "$src" "$WRAPPER_RUN_PATH"
        chmod 755 "$WRAPPER_RUN_PATH"
        chown root:root "$WRAPPER_RUN_PATH"
        log_ok "Installed: $WRAPPER_RUN_PATH"
    else
        log_warn "openbot-run script not found at $src"
    fi
}

copy_config_template() {
    if [[ ! -f "$CONFIG_PATH" ]]; then
        local template="$REPO_DIR/runtime/config.template.yaml"
        local example="$REPO_DIR/runtime/config.example.yaml"

        local src=""
        if [[ -f "$template" ]]; then
            src="$template"
        elif [[ -f "$example" ]]; then
            src="$example"
        fi

        if [[ -n "$src" ]]; then
            cp "$src" "$CONFIG_PATH"
            chown root:"$OPENBOT_GROUP" "$CONFIG_PATH"
            chmod 640 "$CONFIG_PATH"
            log_ok "Copied config template to: $CONFIG_PATH"
            log_warn "EDIT $CONFIG_PATH before running openbot-run"
        else
            log_warn "No config template found, skipping"
        fi
    else
        log_info "Config already exists, skipping"
    fi
}

install_systemd_services() {
    log_info "Installing systemd services..."

    local service_dir="$REPO_DIR/runtime"

    if [[ -f "$service_dir/openbot.service" ]]; then
        cp "$service_dir/openbot.service" /etc/systemd/system/
        log_ok "Installed: openbot.service"
    fi

    if [[ -f "$service_dir/openbot-run.service" ]]; then
        cp "$service_dir/openbot-run.service" /etc/systemd/system/
        log_ok "Installed: openbot-run.service"
    fi

    systemctl daemon-reload
    log_ok "Systemd daemon reloaded"
}

run_mutating_steps() {
    echo ""
    echo "=== Mutating Steps (--yes) ==="
    echo ""

    # Must be root
    if [[ $EUID -ne 0 ]]; then
        log_error "Mutating steps require root. Use: sudo $SCRIPT_NAME --yes"
        exit 1
    fi

    create_user_if_missing
    create_directories
    create_venv
    git_pull
    install_openbot_package
    write_wrapper
    copy_wrapper_run
    copy_config_template
    install_systemd_services

    echo ""
    log_ok "Mutating steps complete"
}

# =============================================================================
# VERIFICATION
# =============================================================================

run_doctor() {
    echo ""
    echo "=== Verification: openbot doctor ==="
    echo ""

    if [[ ! -x "$WRAPPER_PATH" ]]; then
        log_error "Wrapper not found: $WRAPPER_PATH"
        return 1
    fi

    # Run as openbot user if possible
    if id "$OPENBOT_USER" &>/dev/null && [[ $EUID -eq 0 ]]; then
        log_info "Running doctor as $OPENBOT_USER user..."
        cd "$DATA_DIR"
        if sudo -u "$OPENBOT_USER" "$WRAPPER_PATH" doctor; then
            log_ok "Doctor check passed"
        else
            log_fail "Doctor check failed"
            return 1
        fi
    else
        log_info "Running doctor (current user)..."
        if "$WRAPPER_PATH" doctor --local; then
            log_ok "Doctor check passed (local mode)"
        else
            log_fail "Doctor check failed"
            return 1
        fi
    fi
}

verify_paths() {
    echo ""
    echo "=== Path Verification ==="
    echo ""

    echo "Checking wrapper points to correct venv..."
    if [[ -f "$WRAPPER_PATH" ]]; then
        if grep -q "/var/lib/openbot/venv" "$WRAPPER_PATH"; then
            log_ok "Wrapper uses correct venv path"
        else
            log_fail "Wrapper does NOT use /var/lib/openbot/venv"
        fi
    fi

    echo ""
    echo "Resolved paths:"
    echo "  Repo:        $REPO_DIR"
    echo "  Venv:        $VENV_DIR"
    echo "  Wrapper:     $WRAPPER_PATH"
    echo "  Config:      $CONFIG_PATH"
    echo "  Credentials: $CREDENTIALS_PATH"
    echo "  Data:        $DATA_DIR/{logs,receipts,workdir}"
}

# =============================================================================
# SERVICES
# =============================================================================

enable_services() {
    echo ""
    echo "=== Enabling Services (--enable-services --yes) ==="
    echo ""

    if [[ $EUID -ne 0 ]]; then
        log_error "Enabling services requires root"
        exit 1
    fi

    systemctl daemon-reload
    systemctl enable openbot.service openbot-run.service
    log_ok "Services enabled"

    # Note: We do NOT start them automatically - they're oneshot services
    log_info "Services are oneshot. To run:"
    log_info "  sudo systemctl start openbot-run"

    echo ""
    systemctl status openbot.service openbot-run.service --no-pager || true
}

# =============================================================================
# SUMMARY
# =============================================================================

print_summary() {
    echo ""
    echo "============================================================"
    echo "                    INSTALLATION SUMMARY"
    echo "============================================================"
    echo ""
    echo "Repo:          $REPO_DIR"
    echo "Venv:          $VENV_DIR"
    echo "Wrapper:       $WRAPPER_PATH"
    echo "Config:        $CONFIG_PATH"
    echo "Credentials:   $CREDENTIALS_PATH"
    echo "Data dirs:     $DATA_DIR/{logs,receipts,workdir}"
    echo ""

    if [[ -f /etc/systemd/system/openbot.service ]]; then
        echo "Services:"
        systemctl is-enabled openbot.service 2>/dev/null && echo "  openbot.service: enabled" || echo "  openbot.service: disabled"
        systemctl is-enabled openbot-run.service 2>/dev/null && echo "  openbot-run.service: enabled" || echo "  openbot-run.service: disabled"
    fi

    echo ""
    echo "Next steps:"
    echo "  1. Edit config:    sudo vim $CONFIG_PATH"
    echo "  2. Add credentials: sudo vim $CREDENTIALS_PATH"
    echo "  3. Run doctor:     sudo -u openbot $WRAPPER_PATH doctor"
    echo "  4. Test run:       sudo systemctl start openbot-run"
    echo "  5. Check logs:     journalctl -u openbot-run --no-pager"
    echo ""
    echo "============================================================"
}

write_receipt() {
    local receipt_dir="$DATA_DIR/receipts"
    if [[ -d "$receipt_dir" && -w "$receipt_dir" ]]; then
        local receipt_file="$receipt_dir/install_$(date +%Y%m%d_%H%M%S).json"
        cat > "$receipt_file" <<EOF
{
  "type": "install",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "version": "$VERSION",
  "flags": {
    "yes": $FLAG_YES,
    "no_pull": $FLAG_NO_PULL,
    "doctor_only": $FLAG_DOCTOR_ONLY,
    "enable_services": $FLAG_ENABLE_SERVICES
  },
  "paths": {
    "repo": "$REPO_DIR",
    "venv": "$VENV_DIR",
    "config": "$CONFIG_PATH",
    "credentials": "$CREDENTIALS_PATH",
    "data": "$DATA_DIR"
  },
  "checks_passed": $CHECKS_PASSED,
  "checks_failed": $CHECKS_FAILED
}
EOF
        chown "$OPENBOT_USER:$OPENBOT_GROUP" "$receipt_file" 2>/dev/null || true
        log_info "Receipt written: $receipt_file"
    fi
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    echo "============================================================"
    echo "  Clawedbot/Openbot Installer v${VERSION}"
    echo "  Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "============================================================"

    parse_args "$@"

    # --print-plan: run checks only, print plan, exit
    if $FLAG_PRINT_PLAN; then
        run_preflight_checks

        echo "=== Planned Actions ==="
        if [[ ${#ACTIONS_PLANNED[@]} -eq 0 ]]; then
            echo "No actions needed - system is configured correctly."
        else
            for action in "${ACTIONS_PLANNED[@]}"; do
                echo "  - $action"
            done
            echo ""
            echo "To execute these actions, run:"
            echo "  sudo $SCRIPT_NAME --yes"
        fi
        exit 0
    fi

    # --doctor-only: just run doctor
    if $FLAG_DOCTOR_ONLY; then
        run_doctor
        exit $?
    fi

    # Normal flow: preflight -> mutate (if --yes) -> verify
    run_preflight_checks

    if $FLAG_YES; then
        run_mutating_steps
        run_doctor
        verify_paths

        if $FLAG_ENABLE_SERVICES; then
            enable_services
        fi

        write_receipt
        print_summary
    else
        echo ""
        echo "=== Planned Actions ==="
        if [[ ${#ACTIONS_PLANNED[@]} -eq 0 ]]; then
            echo "No actions needed - system is configured correctly."
            echo ""
            echo "Run doctor to verify:"
            echo "  $SCRIPT_NAME --doctor-only"
        else
            for action in "${ACTIONS_PLANNED[@]}"; do
                echo "  - $action"
            done
            echo ""
            echo "To execute these actions, run:"
            echo "  sudo $SCRIPT_NAME --yes"
        fi
    fi
}

main "$@"
