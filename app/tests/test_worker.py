from app.worker import handler, sqs_handler
from platform_common import jobs


def test_unparseable_and_unknown_messages_go_back_to_the_queue(monkeypatch):
    seen = []

    def fake_handle(body, lease_seconds):
        seen.append((body["job_id"], lease_seconds))
        return {"a": jobs.DONE, "b": jobs.SKIPPED, "c": jobs.RETRY}[body["job_id"]]

    event = {"Records": [
        {"messageId": "1", "body": '{"type": "invoice.finalized"}'},
        {"messageId": "2", "body": "not json"},
    ]}
    assert sqs_handler(event, None) == {"batchItemFailures": [{"itemIdentifier": "1"}, {"itemIdentifier": "2"}]}

    monkeypatch.setattr(jobs, "handle_message", fake_handle)
    event = {"Records": [{"messageId": m, "body": f'{{"type": "job.run", "job_id": "{m}"}}'} for m in "abc"]}

    class Context:
        def get_remaining_time_in_millis(self):
            return 900_000

    # Only the job that asked to be retried comes back; the lease is the timeout + 1 minute.
    assert handler(event, Context()) == {"batchItemFailures": [{"itemIdentifier": "c"}]}
    assert {lease for _, lease in seen} == {960}


def test_the_sweep_event_sweeps_the_outbox(monkeypatch):
    from platform_common import outbox

    monkeypatch.setattr(outbox, "sweep", lambda: 2)
    assert handler({"task": "sweep_outbox"}, None) == {"resent": 2}
