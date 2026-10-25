from app.worker import sqs_handler


def test_bad_message_is_reported_for_retry_and_good_one_is_not():
    event = {"Records": [
        {"messageId": "1", "body": '{"type": "invoice.finalized"}'},
        {"messageId": "2", "body": "not json"},
    ]}
    assert sqs_handler(event, None) == {"batchItemFailures": [{"itemIdentifier": "2"}]}
