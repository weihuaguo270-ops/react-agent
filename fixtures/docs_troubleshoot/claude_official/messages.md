# Messages API

Use the Messages API to send a list of input messages and receive a model response.

## Request

POST `/v1/messages` with a JSON body containing `model`, `max_tokens`, and `messages`.

The `messages` array alternates user and assistant turns. Each message has a `role` and `content`.

## Response

The response includes `content` blocks. Text blocks have `"type": "text"`.
Stop reasons include `end_turn` and `tool_use`.
