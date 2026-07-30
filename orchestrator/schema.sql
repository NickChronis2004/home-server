CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    tool_name TEXT NOT NULL,
    tool_tier TEXT NOT NULL,
    params_json TEXT,
    result_status TEXT NOT NULL,
    result_summary TEXT,
    duration_ms INTEGER,
    error_code TEXT,
    confirmed BOOLEAN DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_timestamp ON tool_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_name ON tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tier ON tool_calls(tool_tier);
