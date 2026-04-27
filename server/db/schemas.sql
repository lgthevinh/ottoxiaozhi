CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE OR REPLACE FUNCTION current_unix_ms()
RETURNS BIGINT AS $$
    SELECT (floor(extract(epoch from clock_timestamp()) * 1000))::BIGINT;
$$ LANGUAGE SQL;

CREATE OR REPLACE FUNCTION set_updated_at_ms()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at_ms = current_unix_ms();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255),
    email VARCHAR(320) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    phone_number VARCHAR(32) UNIQUE,
    created_at_ms BIGINT NOT NULL DEFAULT current_unix_ms(),
    updated_at_ms BIGINT NOT NULL DEFAULT current_unix_ms()
);

CREATE TABLE IF NOT EXISTS devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_mac VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(255),
    firmware_version VARCHAR(64),
    audio_sample_rate INTEGER NOT NULL DEFAULT 16000,
    audio_channels INTEGER NOT NULL DEFAULT 1,
    audio_bit_depth INTEGER NOT NULL DEFAULT 16,
    last_active_at_ms BIGINT,
    created_at_ms BIGINT NOT NULL DEFAULT current_unix_ms(),
    updated_at_ms BIGINT NOT NULL DEFAULT current_unix_ms()
);

CREATE INDEX IF NOT EXISTS idx_devices_owner_user_id ON devices(owner_user_id);

DROP TRIGGER IF EXISTS trg_users_set_updated_at_ms ON users;
CREATE TRIGGER trg_users_set_updated_at_ms
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION set_updated_at_ms();

DROP TRIGGER IF EXISTS trg_devices_set_updated_at_ms ON devices;
CREATE TRIGGER trg_devices_set_updated_at_ms
BEFORE UPDATE ON devices
FOR EACH ROW
EXECUTE FUNCTION set_updated_at_ms();
