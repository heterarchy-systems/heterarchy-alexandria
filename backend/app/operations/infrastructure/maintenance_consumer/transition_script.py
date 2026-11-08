"""Lua transition script used by the Redis maintenance consumer."""

from __future__ import annotations

from typing import Final

TRANSITION_MAINTENANCE_JOB_SCRIPT: Final[str] = """
-- TRANSITION_MAINTENANCE_JOB
local function reject(reason)
  return {'REJECTED', reason}
end

local function stream_field(fields, field_name)
  for index = 1, #fields, 2 do
    if fields[index] == field_name then
      return fields[index + 1]
    end
  end
  return false
end

local function failure_fields_match(fields, job_id, kind, attempts, error_summary,
    source_stream_id, history)
  return stream_field(fields, 'job_id') == job_id
    and stream_field(fields, 'kind') == kind
    and stream_field(fields, 'attempts') == attempts
    and stream_field(fields, 'error_summary') == error_summary
    and stream_field(fields, 'source_stream_id') == source_stream_id
    and stream_field(fields, 'attempt_history_json') == history
    and stream_field(fields, 'failed_at') ~= false
end

local function next_dead_letter_id()
  local last_generated_id = '0-0'
  if redis.call('TYPE', KEYS[3]).ok == 'stream' then
    local info = redis.call('XINFO', 'STREAM', KEYS[3])
    for index = 1, #info - 1, 2 do
      if info[index] == 'last-generated-id' then
        last_generated_id = info[index + 1]
        break
      end
    end
  end
  local last_milliseconds = tonumber(string.match(last_generated_id, '^(%d+)%-'))
  if not last_milliseconds then
    return false
  end
  local clock = redis.call('TIME')
  local milliseconds = tonumber(clock[1]) * 1000
    + math.floor(tonumber(clock[2]) / 1000)
  if milliseconds <= last_milliseconds then
    milliseconds = last_milliseconds + 1
  end
  return string.format('%.0f-0', milliseconds)
end

local function publish_or_repair_failed_ack(new_publication)
  redis.call('PERSIST', KEYS[1])
  local job_id = redis.call('HGET', KEYS[1], 'job_id')
  local kind = redis.call('HGET', KEYS[1], 'kind')
  local attempts = redis.call('HGET', KEYS[1], 'attempts')
  local error_summary = redis.call('HGET', KEYS[1], 'error_summary')
  local failed_at = redis.call('HGET', KEYS[1], 'finished_at')
  local history = redis.call('HGET', KEYS[1], 'attempt_history_json')
  local source_stream_id = redis.call('HGET', KEYS[1], 'stream_id')
  local dlq_state = redis.call('HGET', KEYS[1], 'dlq_state')
  if not job_id or not kind or not attempts or not error_summary
      or error_summary == '' or not failed_at or failed_at == ''
      or not history or history == '' or history == '[]'
      or source_stream_id ~= ARGV[2] or not dlq_state or dlq_state == 'RETIRED' then
    return false
  end

  local function finish_ack(entry_id)
    redis.call('HSET', KEYS[1], 'dlq_entry_id', entry_id)
    redis.call('EXPIRE', KEYS[1], ARGV[19])
    redis.call('XACK', KEYS[2], ARGV[21], source_stream_id)
    return true
  end

  local pointer = redis.call('HGET', KEYS[1], 'dlq_entry_id') or ''
  if pointer ~= '' then
    if not string.match(pointer, '^%d+%-%d+$') then
      return false
    end
    if redis.call('TYPE', KEYS[3]).ok == 'stream' then
      local pointed_entry = redis.call('XRANGE', KEYS[3], pointer, pointer)
      if #pointed_entry > 0 then
        if failure_fields_match(
            pointed_entry[1][2], job_id, kind, attempts, error_summary,
            source_stream_id, history) then
          return finish_ack(pointer)
        end
        return false
      end
    end
    if new_publication then
      redis.call(
        'XADD', KEYS[3], 'MAXLEN', '~', ARGV[20], pointer,
        'job_id', job_id,
        'kind', kind,
        'attempts', attempts,
        'failed_at', failed_at,
        'error_summary', error_summary,
        'source_stream_id', source_stream_id,
        'attempt_history_json', history
      )
      redis.call('EXPIRE', KEYS[1], ARGV[19])
      redis.call('XACK', KEYS[2], ARGV[21], source_stream_id)
      return true
    end
  end

  if redis.call('TYPE', KEYS[3]).ok == 'stream' then
    local existing_entries = redis.call('XRANGE', KEYS[3], '-', '+')
    for _, entry in ipairs(existing_entries) do
      local fields = entry[2]
      if stream_field(fields, 'job_id') == job_id
          and stream_field(fields, 'source_stream_id') == source_stream_id
          and stream_field(fields, 'attempts') == attempts then
        if failure_fields_match(
            fields, job_id, kind, attempts, error_summary,
            source_stream_id, history) then
          return finish_ack(entry[1])
        end
        return false
      end
    end
  end

  local entry_id = next_dead_letter_id()
  if not entry_id then
    return false
  end
  redis.call('HSET', KEYS[1], 'dlq_entry_id', entry_id)
  redis.call(
    'XADD', KEYS[3], 'MAXLEN', '~', ARGV[20], entry_id,
    'job_id', job_id,
    'kind', kind,
    'attempts', attempts,
    'failed_at', failed_at,
    'error_summary', error_summary,
    'source_stream_id', source_stream_id,
    'attempt_history_json', history
  )
  redis.call('EXPIRE', KEYS[1], ARGV[19])
  redis.call('XACK', KEYS[2], ARGV[21], source_stream_id)
  return true
end

if redis.call('TYPE', KEYS[1]).ok ~= 'hash' then
  return reject('STATUS_MISSING_OR_WRONG_TYPE')
end
if redis.call('TYPE', KEYS[2]).ok ~= 'stream' then
  return reject('SOURCE_STREAM_MISSING_OR_WRONG_TYPE')
end
local dead_letter_type = redis.call('TYPE', KEYS[3]).ok
if dead_letter_type ~= 'none' and dead_letter_type ~= 'stream' then
  return reject('DEAD_LETTER_STREAM_WRONG_TYPE')
end
local group_name = ARGV[21]
redis.call('XPENDING', KEYS[2], group_name)

local source_entries = redis.call('XRANGE', KEYS[2], ARGV[2], ARGV[2])
if #source_entries == 0 then
  return reject('SOURCE_ENTRY_MISSING')
end
local source_fields = source_entries[1][2]
if stream_field(source_fields, 'job_id') ~= ARGV[3]
    or stream_field(source_fields, 'kind') ~= ARGV[4]
    or stream_field(source_fields, 'requested_by') ~= ARGV[10]
    or stream_field(source_fields, 'source_id') ~= ARGV[9]
    or stream_field(source_fields, 'limit') ~= ARGV[11]
    or stream_field(source_fields, 'force') ~= ARGV[12]
    or stream_field(source_fields, 'submitted_at') ~= ARGV[13] then
  return reject('SOURCE_IDENTITY_MISMATCH')
end

local job_id = redis.call('HGET', KEYS[1], 'job_id')
local kind = redis.call('HGET', KEYS[1], 'kind')
local status = redis.call('HGET', KEYS[1], 'status')
local attempts = redis.call('HGET', KEYS[1], 'attempts')
local submitted_at = redis.call('HGET', KEYS[1], 'submitted_at')
local source_id = redis.call('HGET', KEYS[1], 'source_id')
local requested_by = redis.call('HGET', KEYS[1], 'requested_by')
local limit = redis.call('HGET', KEYS[1], 'limit')
local force = redis.call('HGET', KEYS[1], 'force')
local stream_id = redis.call('HGET', KEYS[1], 'stream_id')
local history = redis.call('HGET', KEYS[1], 'attempt_history_json')
local result = redis.call('HGET', KEYS[1], 'result_json') or ''
local finished_at = redis.call('HGET', KEYS[1], 'finished_at') or ''
local actual_error = redis.call('HGET', KEYS[1], 'error_summary') or ''
local dlq_state = redis.call('HGET', KEYS[1], 'dlq_state')
if not job_id or not kind or not status or not attempts or not submitted_at
    or not source_id or not requested_by or not limit or not force
    or not stream_id or not history or dlq_state ~= 'ACTIVE' then
  return reject('STATUS_HASH_INCOMPLETE')
end
if job_id ~= ARGV[3] or kind ~= ARGV[4] or source_id ~= ARGV[9]
    or requested_by ~= ARGV[10] or limit ~= ARGV[11] or force ~= ARGV[12]
    or submitted_at ~= ARGV[13] or stream_id ~= ARGV[2] then
  return reject('STATUS_IDENTITY_MISMATCH')
end
local attempt_number = tonumber(attempts)
if not attempt_number or attempt_number < 0 or attempt_number % 1 ~= 0 then
  return reject('STATUS_ATTEMPT_INVALID')
end

if ARGV[1] == 'ADMIT' then
  if status ~= ARGV[5] or attempts ~= ARGV[6] or history ~= ARGV[7] then
    return reject('ADMISSION_CAS_MISMATCH')
  end
  if status == 'SUCCEEDED' then
    if result == '' or result ~= ARGV[8] or finished_at == '' or history == '[]' then
      return reject('SUCCEEDED_EVIDENCE_MISMATCH')
    end
    redis.call('EXPIRE', KEYS[1], ARGV[19])
    redis.call('XACK', KEYS[2], group_name, stream_id)
    return {'REPLAYED_SUCCEEDED', attempts}
  end
  if status == 'FAILED' then
    if attempt_number < 1 or result ~= '' or finished_at == ''
        or actual_error == '' or history == '[]' then
      return reject('FAILED_EVIDENCE_INVALID')
    end
    if publish_or_repair_failed_ack(false) then
      return {'REPAIRED_FAILED', attempts}
    end
    return reject('FAILED_DLQ_EVIDENCE_CONFLICT')
  end
  if (status ~= 'QUEUED' and status ~= 'RETRYING')
      or finished_at ~= '' or result ~= '' then
    return reject('STATUS_NOT_EXECUTABLE')
  end
  local next_attempt = attempt_number + 1
  if next_attempt > tonumber(ARGV[18]) then
    return reject('ATTEMPT_LIMIT_REACHED')
  end
  redis.call('PERSIST', KEYS[1])
  redis.call(
    'HSET', KEYS[1],
    'status', 'RUNNING',
    'attempts', tostring(next_attempt),
    'started_at', ARGV[14],
    'finished_at', '',
    'result_json', '',
    'error_summary', '',
    'attempt_history_json', ARGV[15]
  )
  return {'ADMITTED', tostring(next_attempt)}
end

if ARGV[1] ~= 'SUCCEEDED' and ARGV[1] ~= 'FAILED' then
  return reject('TRANSITION_MODE_INVALID')
end
if status ~= 'RUNNING' or stream_id ~= ARGV[2]
    or attempts ~= ARGV[6] or history ~= ARGV[7]
    or result ~= '' or finished_at ~= '' then
  return reject('OUTCOME_CAS_MISMATCH')
end
if attempt_number < 1 or history == '[]' then
  return reject('OUTCOME_EVIDENCE_INVALID')
end

if ARGV[1] == 'SUCCEEDED' then
  if ARGV[16] == '' or ARGV[17] ~= '' then
    return reject('SUCCESS_RESULT_INVALID')
  end
  redis.call(
    'HSET', KEYS[1],
    'status', 'SUCCEEDED',
    'finished_at', ARGV[14],
    'result_json', ARGV[16],
    'error_summary', '',
    'attempt_history_json', ARGV[15]
  )
  redis.call('EXPIRE', KEYS[1], ARGV[19])
  redis.call('XACK', KEYS[2], group_name, stream_id)
  return {'PUBLISHED_SUCCEEDED', attempts}
end

if ARGV[17] == '' or ARGV[16] ~= '' then
  return reject('FAILURE_SUMMARY_INVALID')
end
if attempt_number >= tonumber(ARGV[18]) then
  local entry_id = next_dead_letter_id()
  if not entry_id then
    return reject('FAILED_DLQ_ID_UNAVAILABLE')
  end
  redis.call(
    'HSET', KEYS[1],
    'status', 'FAILED',
    'finished_at', ARGV[14],
    'result_json', '',
    'error_summary', ARGV[17],
    'attempt_history_json', ARGV[15],
    'dlq_entry_id', entry_id
  )
  redis.call('PERSIST', KEYS[1])
  if publish_or_repair_failed_ack(true) then
    return {'PUBLISHED_FAILED', attempts}
  end
  return reject('FAILED_DLQ_EVIDENCE_CONFLICT')
end

redis.call(
  'HSET', KEYS[1],
  'status', 'RETRYING',
  'finished_at', '',
  'result_json', '',
  'error_summary', ARGV[17],
  'attempt_history_json', ARGV[15]
)
redis.call('PERSIST', KEYS[1])
return {'PUBLISHED_RETRYING', attempts}
"""
