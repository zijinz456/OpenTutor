# Installing PostgreSQL 17 + pgvector

OpenTutor requires PostgreSQL 17 with the pgvector extension for vector similarity search.

> **Using Docker?** You don't need to install anything manually — `docker compose up -d` uses the `pgvector/pgvector:pg17` image which includes everything.

---

## macOS (Homebrew)

```bash
# Install PostgreSQL 17
brew install postgresql@17

# Start the service
brew services start postgresql@17

# Install pgvector
brew install pgvector

# Create the OpenTutor database and user
psql postgres -c "CREATE ROLE opentutor WITH LOGIN PASSWORD 'REDACTED_DEV_PASSWORD';"
psql postgres -c "CREATE DATABASE opentutor OWNER opentutor;"
psql -d opentutor -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Verify:

```bash
psql -d opentutor -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
# Should show: 0.8.0 (or similar)
```

---

## Ubuntu / Debian

```bash
# Add PostgreSQL APT repository
sudo apt install -y curl ca-certificates
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /usr/share/keyrings/postgresql-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt update

# Install PostgreSQL 17
sudo apt install -y postgresql-17

# Install pgvector
sudo apt install -y postgresql-17-pgvector

# Start PostgreSQL
sudo systemctl enable --now postgresql

# Create database and user
sudo -u postgres psql -c "CREATE ROLE opentutor WITH LOGIN PASSWORD 'REDACTED_DEV_PASSWORD';"
sudo -u postgres psql -c "CREATE DATABASE opentutor OWNER opentutor;"
sudo -u postgres psql -d opentutor -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

---

## Windows

### Option A: WSL2 (Recommended)

Install WSL2 with Ubuntu, then follow the Ubuntu instructions above.

```powershell
wsl --install -d Ubuntu
```

### Option B: Native Windows

1. Download PostgreSQL 17 from [postgresql.org/download/windows](https://www.postgresql.org/download/windows/)
2. Run the installer (includes pgAdmin)
3. Install pgvector:
   - Download the latest release from [github.com/pgvector/pgvector/releases](https://github.com/pgvector/pgvector/releases)
   - Extract and copy files to your PostgreSQL installation directory
   - Or use `vcpkg`: `vcpkg install pgvector`

4. Create the database:
   ```sql
   -- In pgAdmin or psql:
   CREATE ROLE opentutor WITH LOGIN PASSWORD 'REDACTED_DEV_PASSWORD';
   CREATE DATABASE opentutor OWNER opentutor;
   \c opentutor
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

---

## Docker Only (Database Container)

If you only want the database in Docker (running the API and web locally):

```bash
# Start just the database and Redis
docker compose up -d db redis

# Your DATABASE_URL is already configured for this in .env.example:
# postgresql+asyncpg://opentutor:REDACTED_DEV_PASSWORD@localhost:5432/opentutor
```

This is the easiest path if you don't want to install PostgreSQL natively.

---

## Build from Source (Any Platform)

If your package manager doesn't have pgvector:

```bash
# Prerequisites: PostgreSQL dev headers + build tools
# macOS: brew install postgresql@17
# Ubuntu: sudo apt install postgresql-server-dev-17 build-essential git

git clone https://github.com/pgvector/pgvector.git
cd pgvector
git checkout v0.8.0   # or latest release
make
sudo make install

# Then enable it in your database
psql -d opentutor -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

---

## Verify Installation

```bash
psql -d opentutor -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

If you see a version number, you're good to go. Run `alembic upgrade head` in the `apps/api` directory to set up the database schema.
