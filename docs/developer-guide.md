# HireFlow · Developer guide

HireFlow is a recruitment backend and learning project built with three FastAPI services. Candidates register, browse jobs and apply. Recruiters manage their jobs and applicants. Shortlisting creates a pending interview automatically; the assigned recruiter schedules it and records feedback.

Application code uses synchronous endpoints and SQLAlchemy sessions, explicit CRUD, Pydantic schemas, and FastAPI dependencies. Each service owns its PostgreSQL database.

[← Back to the project overview](../README.md)

## Architecture and stack

```text
Client / Swagger
  |
  +--> Auth :8001 ----------------------> Auth PostgreSQL :5433
  |      |                                (auth-db in Docker)
  |      +------------------------------> Redis :6379
  |                                       (login/register counters)
  +--> Recruitment :8002 ---------------> Recruitment PostgreSQL :5434
  |      |                                (recruitment-db in Docker)
  |      +-- sync HTTPX + internal secret --+
  |                                        |
  +--> Interview :8003 <-------------------+
         |
         +------------------------------> Interview PostgreSQL :5435
                                          (interview-db in Docker)

Auth issues JWTs; each API validates them on protected client requests.
```

Inside Docker each API listens on port `8000`. Its dependencies use Docker service names; the diagram shows published host ports used for local development.

- Python 3.12, FastAPI, Uvicorn, Pydantic and pydantic-settings.
- SQLAlchemy 2.x with synchronous `Session`, psycopg and PostgreSQL 17.
- OAuth2 bearer JWTs with PyJWT; Argon2 password hashing through pwdlib.
- Synchronous HTTPX between Recruitment and Interview.
- Redis 7 and redis-py for authentication rate limits.
- pytest, FastAPI TestClient and Docker Compose.

```text
hireflow/
├── .env.example
├── .gitignore
├── docker-compose.yml
├── README.md
├── docs/                      # Developer guide and repository artwork
├── auth-service/
│   ├── app/                   # Auth CRUD, JWT, models, schemas and rate_limit.py
│   ├── tests/                 # Auth and real-Redis rate-limit tests
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── pytest.ini
├── recruitment-service/
│   ├── app/                   # Jobs, applications and interview_client.py
│   ├── tests/
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── pytest.ini
└── interview-service/
    ├── app/                   # Internal creation, access, scheduling, feedback
    ├── tests/
    ├── Dockerfile
    ├── .dockerignore
    ├── requirements.txt
    ├── requirements-dev.txt
    └── pytest.ini
```

In every `app/`, `main.py` defines routes, `models.py` defines database tables, `schemas.py` defines request/response bodies, `database.py` provides sessions and `config.py` reads environment variables. `dependencies.py` provides JWT, role and (for Interview) internal-service authentication dependencies.

## Environment setup

Install Python 3.12 and Docker with the Compose plugin. Run commands from the project root unless a service directory is specified.

For a new checkout:

```bash
cp .env.example .env
```

If `.env` already exists, keep its existing database credentials and add any missing settings from `.env.example`, especially `REDIS_URL` and `RECRUITER_CREATION_SECRET`. Replace the example database passwords. Generate **three different** secrets, each at least 32 characters, for `AUTH_JWT_SECRET`, `INTERNAL_SERVICE_SECRET` and `RECRUITER_CREATION_SECRET`:

```bash
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

Put the generated values in `.env`; do not commit them. `.env` is ignored by Git and excluded from Docker build contexts. Each Python service loads the root `.env`; explicit process environment variables take precedence. Compose injects only the settings each service needs.

| Setting | Purpose / default in `.env.example` |
| --- | --- |
| `AUTH_POSTGRES_USER`, `AUTH_POSTGRES_PASSWORD`, `AUTH_POSTGRES_DB` | Auth database credentials and database name |
| `RECRUITMENT_POSTGRES_USER`, `RECRUITMENT_POSTGRES_PASSWORD`, `RECRUITMENT_POSTGRES_DB` | Recruitment database credentials and database name |
| `INTERVIEW_POSTGRES_USER`, `INTERVIEW_POSTGRES_PASSWORD`, `INTERVIEW_POSTGRES_DB` | Interview database credentials and database name |
| `*_POSTGRES_HOST`, `*_POSTGRES_PORT` | Local API connections: `127.0.0.1`, ports `5433`, `5434`, `5435` respectively |
| `AUTH_JWT_SECRET` | Same signing/verification secret across the three APIs |
| `RECRUITER_CREATION_SECRET` | Auth-only secret required by `POST /auth/recruiters`; at least 32 characters |
| `AUTH_ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token lifetime; `30` |
| `INTERNAL_SERVICE_SECRET` | Shared only by Recruitment and Interview for internal HTTP calls |
| `INTERVIEW_SERVICE_URL` | Local Recruitment destination; `http://127.0.0.1:8003` |
| `REDIS_URL` | Local Auth destination; `redis://127.0.0.1:6379/0` |
| `AUTH_LOGIN_RATE_LIMIT` | Login attempts per client IP per window; `5` |
| `AUTH_REGISTER_RATE_LIMIT` | Registration attempts per client IP per window; `5` |
| `AUTH_RATE_LIMIT_WINDOW_SECONDS` | Counter lifetime; `60` seconds |
| `AUTH_RATE_LIMIT_PREFIX` | Redis key namespace; `hireflow:rate-limit` |
| `DOCKER_*_POSTGRES_HOST`, `DOCKER_*_POSTGRES_PORT` | Container connections: `auth-db`, `recruitment-db`, `interview-db`, all port `5432` |
| `DOCKER_REDIS_URL` | Container Auth destination; `redis://redis:6379/0` |
| `DOCKER_INTERVIEW_SERVICE_URL` | Container Recruitment destination; `http://interview-service:8000` |
| `AUTH_HTTP_PORT`, `RECRUITMENT_HTTP_PORT`, `INTERVIEW_HTTP_PORT` | Published API ports; `8001`, `8002`, `8003` |
| `AUTH_DB_HOST_PORT`, `RECRUITMENT_DB_HOST_PORT`, `INTERVIEW_DB_HOST_PORT` | Published PostgreSQL ports; `5433`, `5434`, `5435` |
| `REDIS_HOST_PORT` | Published Redis port; `6379` |

The `DOCKER_` settings are read by Compose and supplied under the normal Python setting names inside containers. Python contains no Docker-specific hostnames. If you change published infrastructure ports, change the matching local connection values too. Published API ports also need to match the local Uvicorn commands and local `INTERVIEW_SERVICE_URL` when using local APIs.

## Local development

Start infrastructure only:

```bash
docker compose up -d auth-db recruitment-db interview-db redis
docker compose ps
```

PostgreSQL uses a separate persistent volume for each service. No service reads another service's database. Tables are created at API startup with `Base.metadata.create_all(engine)`. This creates missing tables; it does not migrate existing table definitions. Changing PostgreSQL initialization credentials in `.env` does not update users inside an already initialized volume.

Install requirements and run each API in a separate terminal. These commands use macOS/Linux virtual environments; on Windows, activate with `.venv\Scripts\activate`.

Auth on port 8001:

```bash
cd auth-service
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8001 --no-proxy-headers
```

Recruitment on port 8002:

```bash
cd recruitment-service
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8002 --no-proxy-headers
```

Interview on port 8003:

```bash
cd interview-service
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8003 --no-proxy-headers
```

All three APIs expose `GET /health`, returning their service name and `status="healthy"`. Start Interview before trying to shortlist. `--no-proxy-headers` ensures rate limiting uses the direct peer IP rather than an untrusted forwarded address.

## Complete Docker setup

After configuring `.env`, start the complete project:

```bash
docker compose up --build
```

Or build and run in the background, waiting for healthy services:

```bash
docker compose up --build -d --wait
docker compose ps
```

Compose runs `auth-service`, `recruitment-service`, `interview-service`, `auth-db`, `recruitment-db`, `interview-db` and `redis`. All published ports bind to `127.0.0.1`. API containers run as a non-root user and include application code and runtime dependencies only.

PostgreSQL healthchecks use `pg_isready`; Redis uses `PING`; API healthchecks request `/health` using Python's standard library. Compose waits for healthy dependencies before starting dependent APIs. API health is a liveness check, not a continuous database/Redis readiness check.

```bash
docker compose config --quiet
docker compose logs -f auth-service recruitment-service interview-service
docker compose down
```

`down` stops and removes containers and the Compose network but preserves the named PostgreSQL volumes. `docker compose down --volumes` deletes database data; use it only when you intentionally want a fresh database.

Stop local Uvicorn processes before using the complete Docker setup. To switch back to local APIs, run `docker compose down`, then start the four infrastructure services with the local-development command above. Both modes use the same database volumes when run under the same Compose project.

## JWT authentication and roles

| Auth endpoint | Behavior |
| --- | --- |
| `POST /auth/register` | JSON `name`, `email`, `password`; returns candidate profile with `201`; duplicate email is `409` |
| `POST /auth/recruiters` | Secret header required; JSON `name`, `email`, `password`; creates recruiter with `201`; duplicate email is `409` |
| `POST /auth/token` | OAuth2 form fields `username` (the email) and `password`; returns bearer JWT; invalid credentials are `401` |
| `GET /users/me` | Requires bearer JWT; returns the current active user's public profile |

Passwords use Argon2. Responses never include `password_hash`. Auth validation errors return error locations/messages/types without echoing submitted input values, including invalid passwords.

Tokens contain only `sub`, `role` and `exp`. Every service checks the HS256 signature, expiry and required claims. Send `Authorization: Bearer <access_token>` on protected requests. Auth also checks that the account still exists, is active and has the token's role.

Public registration always creates a `candidate`; submitted role/ownership fields cannot grant privileges. Candidates read jobs, apply, and see their own applications and interviews. Recruiters create/manage their own jobs, review those jobs' applications, and manage assigned interviews. Admins can perform administrative job, application-status and interview operations.

For this MVP, create recruiters directly through **`POST /auth/recruiters`**, using the secret configured in `RECRUITER_CREATION_SECRET`. No manual PostgreSQL role update is needed. In Auth's Swagger UI, expand the endpoint, select **Try it out**, fill `X-Recruiter-Creation-Secret` with the configured secret, and submit:

```json
{
  "name": "Test Recruiter",
  "email": "recruiter@example.com",
  "password": "choose-a-unique-password"
}
```

Only these three body fields are accepted; extra fields such as `role` are rejected with `422`. The backend always assigns `recruiter`, hashes the password with the existing Argon2 helper, and returns the existing safe `UserResponse` with `201`. Missing or incorrect secret headers return `401`. An existing email returns `409`, including an email already registered as a candidate; this endpoint does not promote existing accounts.

The secret is checked by a small `Header`/`Depends()` dependency, just like the existing internal Interview endpoint. It uses `compare_digest` to compare secrets without early-exit timing differences. This protects recruiter creation without adding a new authentication framework. Keep this secret with the developer operating the MVP; a user JWT alone does not authorize this endpoint. Compose passes it only to Auth, and local Auth reads it from the root `.env`.

After creation, log in normally at `POST /auth/token` using the recruiter's email as `username`. The issued JWT contains `role="recruiter"`. Public `POST /auth/register` remains candidate-only; this endpoint cannot create admin accounts.

## Jobs and applications

All Recruitment endpoints require a valid JWT.

| Endpoint | Access / behavior |
| --- | --- |
| `POST /jobs` | Recruiter/admin; owner ID comes from JWT; returns `201` |
| `GET /jobs` | Authenticated users; optional `location`, `active`, `limit` (default 20, max 100), `offset` (default 0) |
| `GET /jobs/{job_id}` | Authenticated users |
| `PUT /jobs/{job_id}` | Owner recruiter/admin; replaces editable fields |
| `DELETE /jobs/{job_id}` | Owner recruiter/admin; sets `active=false`, preserves job and applications, returns `204` |
| `POST /jobs/{job_id}/apply` | Candidate; optional `cover_note`, candidate ID from JWT; returns `201` |
| `GET /applications/me` | Candidate's own applications |
| `GET /jobs/{job_id}/applications` | Job owner/admin |
| `PATCH /applications/{application_id}/status` | Job owner/admin; JSON `status` |

Job fields include title, description, required skills, location, experience, salary range and active flag. Location filtering is an exact match after trimming whitespace. Omitting `active` includes open and closed jobs.

Application statuses are `APPLIED`, `UNDER_REVIEW`, `SHORTLISTED` and `REJECTED`. Applying twice to the same job or applying to a closed job returns `409`. Database uniqueness also prevents concurrent duplicate applications. Missing resources return `404`; authenticated users without permission receive `403`; missing or invalid credentials receive `401`.

## Interview workflow and HTTPX communication

1. Candidate registers and logs in; a provisioned recruiter logs in and creates a job.
2. Candidate lists jobs and applies; recruiter reads the job's applications.
3. Recruiter sends `PATCH /applications/{id}/status` with `{"status":"SHORTLISTED"}`.
4. Recruitment validates the JWT, role and job ownership, then synchronously calls Interview's `POST /internal/interviews` using HTTPX. It sends `application_id`, `candidate_id`, the job owner's `recruiter_id`, and `X-Internal-Service-Secret`.
5. Interview validates the secret through `Depends(require_internal_service)` and creates a `PENDING` record with no schedule, meeting link or feedback. The default type is `VIDEO`.
6. After Interview confirms creation or an existing matching record, Recruitment commits `SHORTLISTED` and returns the updated application.
7. Candidate reads their interview; the assigned recruiter schedules it and submits feedback.

Clients do not manually create interviews. The internal endpoint returns `201` on creation, `200` for a repeat with the same application and participants, and `409` for conflicting participants. A unique application ID prevents duplicates, including on retries. Invalid or missing internal credentials return `401`; a normal user JWT does not replace the internal secret.

HTTPX uses a five-second timeout and does not follow redirects. Timeouts, connection/transport failures, invalid internal credentials, unexpected downstream statuses, malformed receipts and mismatched participant IDs become a generic `503` from Recruitment. Recruitment does not save `SHORTLISTED` on those failures; retry the same request when Interview is available.

| Interview endpoint | Access / behavior |
| --- | --- |
| `GET /interviews` | Candidate's own, recruiter's assigned, or all for admin |
| `GET /interviews/{id}` | Same ownership rules |
| `PATCH /interviews/{id}/status` | Assigned recruiter/admin; status and optional scheduling fields |
| `POST /interviews/{id}/feedback` | Assigned recruiter/admin; JSON `feedback`; replaces previous feedback |
| `POST /internal/interviews` | Recruitment's internal service secret required |

Statuses are `PENDING`, `SCHEDULED`, `COMPLETED` and `CANCELLED`. Types are `VIDEO`, `PHONE` and `IN_PERSON`. To schedule:

```json
{
  "status": "SCHEDULED",
  "scheduled_at": "2026-10-15T10:00:00+05:30",
  "interview_type": "VIDEO",
  "meeting_link": "https://example.com/meeting"
}
```

Use the intended interview date and include a timezone. `SCHEDULED` requires a non-null schedule. Candidates cannot change status or submit feedback. Feedback is included in interview responses and is therefore visible to the candidate who owns that interview.

## Redis rate limiting

Auth's normal route dependencies run the limiter before registration/password verification. Login and registration each allow **five attempts per direct client IP per 60 seconds** by default. Successful requests and failed login/duplicate-registration attempts count. Counters for the two endpoints are independent; unrelated API endpoints are not limited.

Keys look like `hireflow:rate-limit:login:127.0.0.1` and `hireflow:rate-limit:register:127.0.0.1`. A small Redis transaction runs `INCR`, `EXPIRE ... NX` and `TTL`. `NX` sets expiry only if absent, so later attempts do not extend the window. This also keeps creation of the counter and its expiration together if concurrent workers make requests.

Attempt six returns `429 Too Many Requests` with `Retry-After` in seconds. Once Redis expires the key, a fresh window starts. Redis connection/socket timeouts are two seconds; if Redis is unavailable, registration and login return a generic `503` instead of bypassing the limit. No Redis caching is used.

This is a fixed window, not a sliding window. People behind the same NAT share a limit. Proxy headers are disabled by the provided startup commands, so deploying behind a proxy needs deliberate trusted-proxy/IP configuration. Redis is used for temporary counters; losing/recreating its data resets limits.

## Testing

Configure `.env` and start the four infrastructure containers. Tests require PostgreSQL; Auth rate-limit tests also require Redis 7 or later. A running Interview API is not needed by Recruitment's automated suite because HTTPX is mocked there.

Run each suite separately, using that service's virtual environment:

```bash
cd auth-service
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

```bash
cd recruitment-service
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

```bash
cd interview-service
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Each suite creates a uniquely named PostgreSQL schema, uses transactions/savepoints for per-test isolation, and drops only its own schema afterward. The database user needs permission to create schemas. Auth uses unique Redis namespaces and deletes only its test keys; it never flushes Redis.

Optional process environment variables `AUTH_TEST_DATABASE_URL`, `RECRUITMENT_TEST_DATABASE_URL`, `INTERVIEW_TEST_DATABASE_URL` and `AUTH_TEST_REDIS_URL` can point tests at separate infrastructure. Otherwise the tests use the configured local connections. These test-only overrides are read from the process environment.

Coverage includes candidate registration, secret-protected recruiter creation, login, hidden passwords/hashes, JWT signature/expiry/claims, roles, CRUD, ownership, duplicate applications, internal authentication, shortlist HTTPX calls and failure handling, interview scheduling/feedback, and Redis limits/expiry/outages. For a manual end-to-end check, follow the interview workflow above with all three APIs running.

## Swagger

| Service | Swagger UI |
| --- | --- |
| Auth | http://127.0.0.1:8001/docs |
| Recruitment | http://127.0.0.1:8002/docs |
| Interview | http://127.0.0.1:8003/docs |

In Auth's **Authorize** dialog, use your email in the username field. In Recruitment and Interview, paste the Auth access token into **Authorize**. Use the ports you configured if you changed the defaults.

## Concepts beyond basic CRUD and MVP limits

- **Redis transaction and TTL:** a few Redis commands update a shared counter and expiry together. The limiter is an ordinary `Depends()` dependency and raises `HTTPException`, like a role check. [Redis expiry options](https://redis.io/docs/latest/commands/expire/) and [redis-py transactions](https://redis.io/docs/latest/develop/clients/redis-py/transpipe/) explain these commands.
- **Validation exception handler:** FastAPI's default error details can contain submitted input. Auth overrides the handler to retain useful errors while omitting password-bearing values. This is FastAPI's normal exception-handler mechanism; see [handling errors](https://fastapi.tiangolo.com/tutorial/handling-errors/).
- **Retry-safe HTTP creation:** a unique application ID makes repeat shortlist calls return the same interview. It complements ordinary SQLAlchemy uniqueness checks and `IntegrityError` handling; no queue or distributed-transaction framework is used.
- **Test savepoints:** endpoint commits stay inside an outer transaction that tests can roll back, isolating CRUD tests without changing production session handling.
- **Docker health dependencies:** Compose waits for PostgreSQL, Redis and Interview healthchecks before starting dependent APIs. See [Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/).

Recruitment and Interview commit to separate databases. If Interview commits and Recruitment later fails, a pending interview can temporarily exist before the application is shortlisted. Retrying repairs that case; there is no automatic reconciliation. Only one interview is supported per application, with no feedback history or calendar integration. Rejecting an application does not automatically cancel its interview, and a full status-transition policy is not enforced.

Recruitment and Interview validate JWT claims locally; they do not immediately see Auth role changes or account deactivation, so an already issued token can remain usable there until expiry. This MVP uses local HTTP and shared secrets, no refresh tokens, no migration system, and no proxy layer. Requirements use bounded version ranges rather than a fully locked dependency set.
