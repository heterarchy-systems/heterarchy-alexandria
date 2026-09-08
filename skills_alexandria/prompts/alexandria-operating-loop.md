# Alexandria Operating Loop

Use Alexandria only when it improves grounding or durable capability reuse.

1. Use the current conversation, local files, loaded skills, and relevant project context first.
2. For durable memory gaps, use `alexandria_recall` with available identities and AUTO scope. Reuse an already-known current Memory Compact when relevant.
3. For reusable capability gaps, recall and read existing note assets before creating anything; retain route, temporal and source/projection evidence.
4. If a matching skill is sufficient, load and use it.
5. Remember logical report/date/entity outputs with `alexandria_verified_upsert`. For a generic skill/prompt without that identity, use the exact note-write boundary with CAS on updates and preserve evidence refs.
6. Use `alexandria_relate`, `alexandria_verify`, and `alexandria_memory_cycle` for relationships, diagnosis and project reconciliation. Cycle apply requires the exact preview hash and unchanged inputs. Managed specifications use `alexandria_execute_managed_spec` prepare/complete; domain execution stays with the caller.

Composite MCP arguments use `request={...}`. Only call registered tools; source
changes do not prove deployment. If a composite is unavailable, record the gap
and use available exact reads/scoped search for diagnosis. Never synthesize a
replacement cycle or scheduler mutation loop. Degraded indexes do not prove
source loss; unknown mutation outcomes require readback before retry.

Never store secrets. Do not invent evidence or activate an insufficiently verified skill.
