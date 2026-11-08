"""Lua scripts used by the Redis maintenance queue adapter."""

from __future__ import annotations

from typing import Final

ENQUEUE_MAINTENANCE_JOB_SCRIPT: Final[str] = """
local existing = redis.call('GET', KEYS[1])
if existing then
  return {'DEDUPLICATED', existing, ''}
end

local current = redis.call('INCR', KEYS[4])
if current == 1 then
  redis.call('EXPIRE', KEYS[4], ARGV[1])
end
if current > tonumber(ARGV[2]) then
  local ttl = redis.call('TTL', KEYS[4])
  return {'RATE_LIMITED', tostring(ttl), ''}
end

local stream_id = redis.call(
  'XADD', KEYS[2], 'MAXLEN', '~', ARGV[3], '*',
  'job_id', ARGV[4],
  'kind', ARGV[5],
  'requested_by', ARGV[6],
  'source_id', ARGV[7],
  'limit', ARGV[8],
  'force', ARGV[9],
  'submitted_at', ARGV[10]
)
redis.call(
  'HSET', KEYS[3],
  'job_id', ARGV[4],
  'kind', ARGV[5],
  'status', 'QUEUED',
  'requested_by', ARGV[6],
  'source_id', ARGV[7],
  'limit', ARGV[8],
  'force', ARGV[9],
  'attempts', '0',
  'submitted_at', ARGV[10],
  'stream_id', stream_id,
  'result_json', '',
  'error_summary', '',
  'attempt_history_json', '[]',
  'last_retry_reason', '',
  'last_retry_at', '',
  'dlq_state', 'ACTIVE',
  'dlq_entry_id', ''
)
redis.call('SET', KEYS[1], ARGV[4], 'EX', ARGV[11])
return {'QUEUED', ARGV[4], stream_id}
"""

RETRY_MAINTENANCE_DEAD_LETTER_SCRIPT: Final[str] = """
local status = redis.call('HGET', KEYS[1], 'status')
if not status then
  return {'NOT_FOUND', '', ''}
end
local lifecycle = redis.call('GET', KEYS[4]) or 'ACTIVE'
if string.sub(lifecycle, 1, 8) == 'RETRIED:' and (status == 'QUEUED' or status == 'RUNNING' or status == 'RETRYING' or status == 'SUCCEEDED') then
  return {'IDEMPOTENT', redis.call('HGET', KEYS[1], 'job_id') or '', redis.call('HGET', KEYS[1], 'stream_id') or ''}
end
if lifecycle ~= 'ACTIVE' then
  return {'CONFLICT', redis.call('HGET', KEYS[1], 'job_id') or '', lifecycle}
end
if status == 'QUEUED' or status == 'RUNNING' or status == 'RETRYING' or status == 'SUCCEEDED' then
  return {'IDEMPOTENT', redis.call('HGET', KEYS[1], 'job_id') or '', redis.call('HGET', KEYS[1], 'stream_id') or ''}
end
if status ~= 'FAILED' then
  return {'CONFLICT', redis.call('HGET', KEYS[1], 'job_id') or '', lifecycle}
end
local original_stream_id = redis.call('HGET', KEYS[1], 'stream_id')
if original_stream_id and ARGV[5] ~= '' then
  local pending = redis.call('XPENDING', KEYS[2], ARGV[5], original_stream_id, original_stream_id, 1)
  if #pending > 0 then
    return {'CONFLICT', redis.call('HGET', KEYS[1], 'job_id') or '', 'ACTIVE_DELIVERY'}
  end
end
local entries = redis.call('XRANGE', KEYS[3], ARGV[1], ARGV[1])
if #entries == 0 then
  return {'NOT_FOUND', '', ''}
end
local stream_id = redis.call(
  'XADD', KEYS[2], 'MAXLEN', '~', ARGV[2], '*',
  'job_id', redis.call('HGET', KEYS[1], 'job_id'),
  'kind', redis.call('HGET', KEYS[1], 'kind'),
  'requested_by', redis.call('HGET', KEYS[1], 'requested_by'),
  'source_id', redis.call('HGET', KEYS[1], 'source_id'),
  'limit', redis.call('HGET', KEYS[1], 'limit'),
  'force', redis.call('HGET', KEYS[1], 'force'),
  'submitted_at', redis.call('HGET', KEYS[1], 'submitted_at')
)
redis.call(
  'HSET', KEYS[1],
  'status', 'QUEUED',
  'attempts', '0',
  'started_at', '',
  'finished_at', '',
  'stream_id', stream_id,
  'result_json', '',
  'error_summary', '',
  'dlq_entry_id', '',
  'dlq_state', 'ACTIVE',
  'last_retry_reason', ARGV[3],
  'last_retry_at', ARGV[4]
)
redis.call('PERSIST', KEYS[1])
redis.call('SET', KEYS[4], 'RETRIED:' .. redis.call('HGET', KEYS[1], 'job_id'))
return {'QUEUED', redis.call('HGET', KEYS[1], 'job_id'), stream_id}
"""

RESERVE_MAINTENANCE_DEAD_LETTER_SCRIPT: Final[str] = """
local status = redis.call('HGET', KEYS[1], 'status')
if not status then
  return {'NOT_FOUND', ''}
end
local lifecycle = redis.call('GET', KEYS[3])
if lifecycle == 'RETIRING' or lifecycle == 'RETIRED' then
  return {lifecycle, status}
end
if status ~= 'FAILED' then
  return {'CONFLICT', status}
end
local source_stream_id = redis.call('HGET', KEYS[1], 'stream_id')
if source_stream_id and ARGV[2] ~= '' then
  local pending = redis.call('XPENDING', KEYS[4], ARGV[2], source_stream_id, source_stream_id, 1)
  if #pending > 0 then
    return {'CONFLICT', 'ACTIVE_DELIVERY'}
  end
end
local entries = redis.call('XRANGE', KEYS[2], ARGV[1], ARGV[1])
if #entries == 0 then
  return {'NOT_FOUND', ''}
end
redis.call('SET', KEYS[3], 'RETIRING')
return {'RETIRING', status}
"""

FINALIZE_MAINTENANCE_DEAD_LETTER_SCRIPT: Final[str] = """
local status = redis.call('HGET', KEYS[1], 'status')
local lifecycle = redis.call('GET', KEYS[4])
if lifecycle == 'RETIRED' then
  return {'ALREADY_RETIRED', '0', '0'}
end
if lifecycle ~= 'RETIRING' or status ~= 'FAILED' then
  return {'CONFLICT', status or '', lifecycle or ''}
end
local removed_dlq = redis.call('XDEL', KEYS[2], ARGV[1])
local removed_source = 0
if ARGV[2] ~= '' then
  removed_source = redis.call('XDEL', KEYS[3], ARGV[2])
end
redis.call('HSET', KEYS[1], 'dlq_state', 'RETIRED')
redis.call('SET', KEYS[4], 'RETIRED')
return {'RETIRED', tostring(removed_dlq), tostring(removed_source)}
"""
