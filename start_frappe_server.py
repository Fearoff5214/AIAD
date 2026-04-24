import argparse
import os
import subprocess
import sys
import time


CORE_SERVICES = [
    "backend",
    "configurator",
    "db",
    "frontend",
    "queue-long",
    "queue-short",
    "redis-queue",
    "redis-cache",
    "scheduler",
    "websocket",
]


def check_docker_daemon():
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("\n" + "!" * 60)
        print("ERROR: Docker Desktop is not running!")
        print("Please start Docker Desktop and try again.")
        print("!" * 60 + "\n")
        sys.exit(1)


def print_access_links(tenants, frontend_port):
    print("\nServer started successfully.")
    print("Website links:")
    print(f"- Main site: http://localhost:{frontend_port}")
    print(f"- GST Copilot: http://localhost:{frontend_port}/gst-copilot")
    print(f"- Create Account: http://localhost:{frontend_port}/user-register")

    if len(tenants) > 1:
        print("- Tenant domains:")
        for site in tenants[1:]:
            print(f"  - http://{site}:{frontend_port}")
        print("- Note: Add tenant domains to your hosts file if they do not resolve locally.")


def run(cmd, cwd, check=True, capture_output=False):
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture_output,
    )


def wait_for_db_health(cwd, timeout_seconds=180):
    start = time.time()
    while time.time() - start < timeout_seconds:
        result = run(
            ["docker", "compose", "ps", "db"],
            cwd=cwd,
            check=False,
            capture_output=True,
        )
        if "healthy" in (result.stdout or ""):
            # Extra settle time so MariaDB fully initialises table definitions
            print("Database healthy. Waiting 15 s for full table initialisation...")
            time.sleep(15)
            return
        time.sleep(3)
    raise TimeoutError("Timed out waiting for database health check")


def wait_for_backend_container(cwd, timeout_seconds=180):
    start = time.time()
    while time.time() - start < timeout_seconds:
        result = run(
            ["docker", "compose", "ps", "backend"],
            cwd=cwd,
            check=False,
            capture_output=True,
        )
        if "Up" in (result.stdout or ""):
            return
        time.sleep(3)
    raise TimeoutError("Timed out waiting for backend container")


def wait_for_service_container(cwd, service, timeout_seconds=300):
    start = time.time()
    while time.time() - start < timeout_seconds:
        result = run(
            ["docker", "compose", "ps", service],
            cwd=cwd,
            check=False,
            capture_output=True,
        )
        if "Up" in (result.stdout or ""):
            return
        time.sleep(3)
    raise TimeoutError(f"Timed out waiting for {service} container")


def site_exists(cwd, site):
    result = run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "backend",
            "bash",
            "-lc",
            f"test -d sites/{site}",
        ],
        cwd=cwd,
        check=False,
    )
    return result.returncode == 0


def ensure_site_alias(cwd, alias_name, target_site):
    run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "backend",
            "bash",
            "-lc",
            f"cd sites && ln -sfn {target_site} {alias_name}",
        ],
        cwd=cwd,
    )


def installed_apps(cwd, site):
    result = run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "backend",
            "bench",
            "--site",
            site,
            "list-apps",
        ],
        cwd=cwd,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def install_app_with_retry(cwd, site, app, max_retries=5, delay=20):
    """Install a bench app, retrying on transient MariaDB error 1412."""
    for attempt in range(1, max_retries + 1):
        print(f"Installing {app} on {site} (attempt {attempt}/{max_retries})...")
        result = run(
            [
                "docker", "compose", "exec", "-T", "backend",
                "bench", "--site", site, "install-app", app,
            ],
            cwd=cwd,
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            print(f"{app} installed successfully.")
            return
        combined = (result.stdout or "") + (result.stderr or "")
        if "1412" in combined or "Table definition has changed" in combined:
            print(f"  Transient DB error (1412) on {app}, retrying in {delay}s...")
            time.sleep(delay)
        else:
            # Non-retryable error – surface it
            print(result.stdout or "")
            print(result.stderr or "")
            raise subprocess.CalledProcessError(result.returncode, result.args)
    raise RuntimeError(f"Failed to install {app} after {max_retries} attempts.")


def ensure_site(cwd, site, admin_password, db_root_password):
    if not site_exists(cwd, site):
        print(f"Creating tenant site: {site}")
        run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "backend",
                "bench",
                "new-site",
                site,
                "--no-mariadb-socket",
                "--admin-password",
                admin_password,
                "--db-root-username",
                "root",
                "--db-root-password",
                db_root_password,
                "--install-app",
                "erpnext",
                "--install-app",
                "india_compliance",
            ],
            cwd=cwd,
        )

    apps = installed_apps(cwd, site)
    if "erpnext" not in apps:
        install_app_with_retry(cwd, site, "erpnext")

    if "india_compliance" not in apps:
        install_app_with_retry(cwd, site, "india_compliance")


def set_site_hostname(cwd, site, host_name):
    run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "backend",
            "bench",
            "--site",
            site,
            "set-config",
            "host_name",
            host_name,
        ],
        cwd=cwd,
    )


def migrate_site(cwd, site):
    print(f"Running migrate for {site}")
    run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "backend",
            "bench",
            "--site",
            site,
            "migrate",
        ],
        cwd=cwd,
    )


def bootstrap_primary_admin(cwd, site):
    print(f"Ensuring primary admin credentials on {site}")
    run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "backend",
            "bench",
            "--site",
            site,
            "execute",
            "india_compliance.gst_india.api.portal_management.ensure_primary_admin_account",
        ],
        cwd=cwd,
    )


def seed_demo_portal_accounts(cwd, site):
    print(f"Seeding demo portal accounts on {site}")
    run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "backend",
            "bench",
            "--site",
            site,
            "execute",
            "india_compliance.gst_india.api.portal_management.ensure_demo_portal_accounts",
        ],
        cwd=cwd,
    )


def pull_ollama_model(cwd, model):
    print(f"Checking for LLM model: {model}")
    try:
        # Try local ollama command first
        subprocess.run(["ollama", "pull", model], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"Warning: Could not pull {model} via local 'ollama' command.")


def start_ollama_in_background(cwd):
    # No-op as we use host's Ollama
    pass


def parse_tenants(raw_tenants):
    tenants = []
    for item in raw_tenants.split(","):
        site = item.strip()
        if site:
            tenants.append(site)
    return tenants or ["frontend"]


def run_server():
    parser = argparse.ArgumentParser(description="Start Fearoff AIAD in production-ready multi-tenant mode")
    parser.add_argument("--tenants", default=os.getenv("TENANT_SITES", "frontend"))
    parser.add_argument("--admin-password", default=os.getenv("ADMIN_PASSWORD", "admin"))
    parser.add_argument("--db-root-password", default=os.getenv("DB_ROOT_PASSWORD", "admin"))
    parser.add_argument("--ollama-model", default=os.getenv("OLLAMA_MODEL", "deepseek-r1:7b"))
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--skip-migrate", action="store_true")
    parser.add_argument("--skip-ollama-pull", action="store_true")
    parser.add_argument("--skip-ollama-service", default=True, action="store_true")
    parser.add_argument("--follow-logs", action="store_true")
    args = parser.parse_args()

    cwd = os.path.abspath(os.path.dirname(__file__))
    check_docker_daemon()
    tenants = parse_tenants(args.tenants)
    frontend_port = os.getenv("FRONTEND_PORT", "8085")

    try:
        compose_cmd = ["docker", "compose", "up", "-d"]
        if not args.no_build:
            compose_cmd.append("--build")
        compose_cmd.extend(CORE_SERVICES)

        print("Starting core Docker Compose services...")
        run(compose_cmd, cwd=cwd)

        wait_for_db_health(cwd)
        wait_for_backend_container(cwd)

        for idx, site in enumerate(tenants):
            ensure_site(cwd, site, args.admin_password, args.db_root_password)

            host_name = "localhost" if idx == 0 else site
            set_site_hostname(cwd, site, host_name)

            if not args.skip_migrate:
                migrate_site(cwd, site)

            if idx == 0:
                bootstrap_primary_admin(cwd, site)
                seed_demo_portal_accounts(cwd, site)

        # Keep first tenant as default for localhost access.
        run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "backend",
                "bench",
                "use",
                tenants[0],
            ],
            cwd=cwd,
        )

        # Ensure browser access on localhost/127.0.0.1 maps to the default tenant.
        ensure_site_alias(cwd, "localhost", tenants[0])
        ensure_site_alias(cwd, "127.0.0.1", tenants[0])

        wait_for_service_container(cwd, "frontend", timeout_seconds=180)

        print_access_links(tenants, frontend_port)
        print(f"Tenants provisioned: {', '.join(tenants)}")
        print("Use reverse proxy host routing for non-default tenant domains in production.")

        if not args.skip_ollama_service:
            print("Starting Ollama service in background (first pull can take several minutes)...")
            start_ollama_in_background(cwd)

        if not args.skip_ollama_pull:
            try:
                wait_for_service_container(cwd, "ollama", timeout_seconds=900)
                pull_ollama_model(cwd, args.ollama_model)
            except TimeoutError:
                sys.stderr.write(
                    "Warning: Ollama did not become ready in time. The website is up; retry model pull later.\n"
                )

        if args.follow_logs:
            run(["docker", "compose", "logs", "-f"], cwd=cwd)

    except KeyboardInterrupt:
        sys.stderr.write(
            "Startup interrupted by user. Core services that were already started are still running.\n"
        )
        sys.exit(130)
    except (subprocess.CalledProcessError, TimeoutError) as exc:
        sys.stderr.write(f"Startup failed: {exc}\n")
        sys.stderr.write("See STARTUP_TROUBLESHOOTING.md for quick recovery steps.\n")
        sys.exit(1)
    except Exception as exc:
        sys.stderr.write(f"Unexpected startup error: {type(exc).__name__}: {exc}\n")
        sys.stderr.write("See STARTUP_TROUBLESHOOTING.md for quick recovery steps.\n")
        sys.exit(1)


if __name__ == "__main__":
    run_server()
