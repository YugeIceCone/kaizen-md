# Onion Architecture in Rust

Concrete mapping of the four layers onto a Rust workspace using `axum` for the presentation layer, `sqlx` for infrastructure, and traits for the domain ports.

## Workspace layout

```
crates/
├── domain/          # zero deps on infrastructure
├── application/     # depends on domain
├── infrastructure/  # depends on domain (implements ports)
├── presentation/    # depends on application
└── bin/             # composition root — depends on all
```

## Domain (`crates/domain/src/lib.rs`)

```rust
// value_objects/user_id.rs
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct UserId(uuid::Uuid);

impl UserId {
    pub fn fresh() -> Self { Self(uuid::Uuid::new_v4()) }
    pub fn as_str(&self) -> String { self.0.to_string() }
}

impl std::fmt::Display for UserId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

// value_objects/email_address.rs
#[derive(Clone, Debug)]
pub struct EmailAddress(String);

impl EmailAddress {
    pub fn parse(raw: &str) -> Result<Self, DomainError> {
        if !raw.contains('@') {
            return Err(DomainError::InvalidEmail);
        }
        Ok(Self(raw.to_string()))
    }
    pub fn as_str(&self) -> &str { &self.0 }
}

impl std::fmt::Display for EmailAddress {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

// entities/user.rs
pub struct User {
    pub id: UserId,
    name: String,
    email: EmailAddress,
}

impl User {
    pub fn new(id: UserId, name: String, email: EmailAddress) -> Self {
        Self { id, name, email }
    }

    // Read accessors — required by the Postgres adapter. Encapsulation
    // is preserved because callers can't *mutate* state through them.
    pub fn name(&self) -> &str { &self.name }
    pub fn email(&self) -> &EmailAddress { &self.email }

    pub fn rename(&mut self, new_name: String) -> Result<(), DomainError> {
        if new_name.trim().is_empty() {
            return Err(DomainError::InvalidName);
        }
        self.name = new_name;
        Ok(())
    }
}

// errors.rs
#[derive(Debug, thiserror::Error)]
pub enum DomainError {
    #[error("invalid name")]
    InvalidName,
    #[error("invalid email")]
    InvalidEmail,
}

// ports/user_repository.rs
#[async_trait::async_trait]
pub trait UserRepository: Send + Sync {
    async fn save(&self, user: &User) -> Result<(), RepoError>;
    async fn by_id(&self, id: &UserId) -> Result<Option<User>, RepoError>;
}

#[derive(Debug, thiserror::Error)]
pub enum RepoError {
    #[error("storage failure: {0}")]
    Storage(String),
}
```

`Cargo.toml` for domain has no `sqlx`, no `axum`, no `reqwest`. Just `serde`, `thiserror`, `async-trait`, and pure types.

## Application (`crates/application/src/lib.rs`)

```rust
use std::sync::Arc;
use domain::{DomainError, EmailAddress, RepoError, User, UserId, UserRepository};

pub struct RegisterUserCommand {
    pub name: String,
    pub email: String,
}

pub struct RegisterUserResult {
    pub id: String,
}

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("domain rule violated: {0}")]
    Domain(#[from] DomainError),
    #[error("storage error: {0}")]
    Repo(#[from] RepoError),
}

pub struct RegisterUserService {
    users: Arc<dyn UserRepository>,
}

impl RegisterUserService {
    pub fn new(users: Arc<dyn UserRepository>) -> Self { Self { users } }

    pub async fn execute(
        &self,
        cmd: RegisterUserCommand,
    ) -> Result<RegisterUserResult, AppError> {
        let email = EmailAddress::parse(&cmd.email)?;
        let user = User::new(UserId::fresh(), cmd.name, email);
        self.users.save(&user).await?;
        Ok(RegisterUserResult { id: user.id.to_string() })
    }
}
```

The application service holds a trait object — it doesn't know about Postgres. Tests construct it with a `MockUserRepository`.

## Infrastructure (`crates/infrastructure/src/lib.rs`)

```rust
use async_trait::async_trait;
use domain::{User, UserId, UserRepository, RepoError};
use sqlx::PgPool;

pub struct PostgresUserRepository {
    pool: PgPool,
}

impl PostgresUserRepository {
    pub fn new(pool: PgPool) -> Self { Self { pool } }
}

#[async_trait]
impl UserRepository for PostgresUserRepository {
    async fn save(&self, user: &User) -> Result<(), RepoError> {
        sqlx::query!(
            "INSERT INTO users (id, name, email) VALUES ($1, $2, $3)
             ON CONFLICT (id) DO UPDATE SET name = $2, email = $3",
            user.id.to_string(),
            user.name(),
            user.email().to_string(),
        )
        .execute(&self.pool)
        .await
        .map_err(|e| RepoError::Storage(e.to_string()))?;
        Ok(())
    }

    async fn by_id(&self, id: &UserId) -> Result<Option<User>, RepoError> {
        // sqlx::query! returns a row; map to a domain `User`.
        // Body elided for brevity — the shape is:
        //   1. Run SELECT against `self.pool`
        //   2. For each row, parse `email` via `EmailAddress::parse`
        //   3. Call `User::new(...)` to reconstruct the aggregate
        todo!("query by id and reconstruct domain User")
    }
}
```

Owns `sqlx`, the connection pool, the SQL. Knows the schema. Implements the domain trait.

## Presentation (`crates/presentation/src/lib.rs`)

```rust
use axum::{Router, Json, extract::State, http::StatusCode};
use std::sync::Arc;
use application::{RegisterUserService, RegisterUserCommand};

#[derive(serde::Deserialize)]
pub struct RegisterUserBody {
    name: String,
    email: String,
}

#[derive(serde::Serialize)]
pub struct RegisterUserResponse {
    id: String,
}

pub fn user_routes(register: Arc<RegisterUserService>) -> Router {
    Router::new()
        .route("/users", axum::routing::post(handle_register))
        .with_state(register)
}

async fn handle_register(
    State(register): State<Arc<RegisterUserService>>,
    Json(body): Json<RegisterUserBody>,
) -> Result<(StatusCode, Json<RegisterUserResponse>), StatusCode> {
    let result = register
        .execute(RegisterUserCommand { name: body.name, email: body.email })
        .await
        .map_err(|_| StatusCode::BAD_REQUEST)?;
    Ok((StatusCode::CREATED, Json(RegisterUserResponse { id: result.id })))
}
```

Translates `axum` extractors into commands, formats results into HTTP responses.

## Composition root (`crates/bin/src/main.rs`)

```rust
use std::sync::Arc;
use sqlx::postgres::PgPoolOptions;
use infrastructure::PostgresUserRepository;
use application::RegisterUserService;
use presentation::user_routes;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let pool = PgPoolOptions::new().connect(&std::env::var("DATABASE_URL")?).await?;
    let users = Arc::new(PostgresUserRepository::new(pool));
    let register = Arc::new(RegisterUserService::new(users));
    let app = user_routes(register);

    axum::serve(tokio::net::TcpListener::bind("0.0.0.0:3000").await?, app).await?;
    Ok(())
}
```

`bin` is the only crate that depends on every other layer — it does the wiring. `domain` depends on nothing. `application` depends only on `domain`. `infrastructure` depends only on `domain` (to know which traits to implement). `presentation` depends only on `application`.

## Workspace dep graph (in `Cargo.toml` files)

| Crate | Depends on |
|---|---|
| `domain` | (nothing inside the workspace) |
| `application` | `domain` |
| `infrastructure` | `domain` |
| `presentation` | `application` |
| `bin` | `application`, `infrastructure`, `presentation` |

If `domain/Cargo.toml` ever lists another workspace crate as a dep, the architecture has been violated.
