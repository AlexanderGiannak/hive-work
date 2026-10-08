-- Hivework tables. Safe to run again: everything is IF NOT EXISTS.

-- Anything the Recorder bot copies off the board (prices, fair values, etc).
CREATE TABLE IF NOT EXISTS records (
    id      BIGSERIAL PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    topic   TEXT NOT NULL,
    data    JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS records_topic_ts ON records (topic, ts DESC);

-- Every order a trader bot sent (demo or paper), filled or not.
CREATE TABLE IF NOT EXISTS trades (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    hive        TEXT NOT NULL,
    bot         TEXT NOT NULL,
    mode        TEXT NOT NULL,          -- 'demo' or 'paper'
    ticker      TEXT NOT NULL,
    side        TEXT NOT NULL,          -- 'yes' or 'no'
    action      TEXT NOT NULL,          -- 'buy' or 'sell'
    count       INTEGER NOT NULL,       -- contracts asked for
    filled      INTEGER NOT NULL,       -- contracts actually filled
    price       NUMERIC(6,4) NOT NULL,  -- dollars per contract
    fair        NUMERIC(6,4),
    order_id    TEXT,
    status      TEXT NOT NULL,
    detail      JSONB
);
CREATE INDEX IF NOT EXISTS trades_hive_ts ON trades (hive, ts DESC);

-- Exceptions from any bot.
CREATE TABLE IF NOT EXISTS errors (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    hive        TEXT NOT NULL,
    bot         TEXT NOT NULL,
    error       TEXT NOT NULL,
    traceback   TEXT
);
CREATE INDEX IF NOT EXISTS errors_ts ON errors (ts DESC);

-- Things that happened: queen starts and restarts, kill switch flips, risk blocks.
CREATE TABLE IF NOT EXISTS events (
    id      BIGSERIAL PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    hive    TEXT NOT NULL,
    bot     TEXT,
    kind    TEXT NOT NULL,
    detail  TEXT
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts DESC);

-- Numbers over time, for charts.
CREATE TABLE IF NOT EXISTS metrics (
    id      BIGSERIAL PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    hive    TEXT NOT NULL,
    name    TEXT NOT NULL,
    value   DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS metrics_name_ts ON metrics (hive, name, ts DESC);
