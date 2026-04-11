import json
import os
from urllib import error, request

from django.db import transaction
from django.utils import timezone

from .models import ProductChatMessage, ProductChatSession


DASHSCOPE_COMPATIBLE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
DASHSCOPE_MODEL_NAME = 'qwen3.6-plus'


def get_or_create_product_chat_session(user, product):
    session, _ = ProductChatSession.objects.get_or_create(user=user, product=product)
    return session


def serialize_product_chat_messages(session):
    return [
        {
            'id': message.id,
            'role': message.role,
            'content': message.content,
            'created_at': timezone.localtime(message.created_at).strftime('%Y-%m-%d %H:%M'),
        }
        for message in session.messages.all()
    ]


def build_product_context_prompt(product):
    lines = [
        'You are a book guide and reading assistant.',
        'Unless the user explicitly asks for another language, always reply in English.',
        'Use the provided book information together with your general knowledge to give concise, accurate, and helpful answers.',
        'If a conclusion mainly comes from general knowledge rather than the provided book data, say so naturally.',
        'Do not invent specific plot details. If you are unsure, say that clearly.',
        '',
        'Current book information:',
        f'Product ID: {product.product_id}',
        f'Title: {product.title}',
        f'Author: {product.authors or "Unknown"}',
        f'Publisher: {product.publisher or "Unknown"}',
        f'Published date: {product.published_date or "Unknown"}',
        f'Category: {product.category or "Unknown"}',
        f'Description: {product.description or "No description available"}',
    ]
    return '\n'.join(lines)


def build_llm_messages(product, prior_messages, user_message=None, intro_mode=False):
    messages = [
        {
            'role': 'system',
            'content': build_product_context_prompt(product),
        }
    ]

    for message in prior_messages:
        messages.append({
            'role': message.role,
            'content': message.content,
        })

    if intro_mode:
        messages.append({
            'role': 'user',
            'content': 'Please start with a short 2 to 4 sentence review or summary of this book as the opening message.',
        })
    elif user_message:
        messages.append({
            'role': 'user',
            'content': user_message,
        })

    return messages


def _build_request_payload(messages, stream=False):
    payload = {
        'model': DASHSCOPE_MODEL_NAME,
        'messages': messages,
        'temperature': 0.7,
    }
    if stream:
        payload['stream'] = True
        payload['stream_options'] = {'include_usage': True}
    return json.dumps(payload).encode('utf-8')


def _build_dashscope_request(messages, stream=False):
    api_key = os.getenv('DASHSCOPE_API_KEY')
    if not api_key:
        raise RuntimeError('DASHSCOPE_API_KEY is not set. Please restart the server after running setx.')

    return request.Request(
        DASHSCOPE_COMPATIBLE_URL,
        data=_build_request_payload(messages, stream=stream),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )


def call_dashscope_chat_api(messages):
    req = _build_dashscope_request(messages, stream=False)

    try:
        with request.urlopen(req, timeout=45) as response:
            data = json.loads(response.read().decode('utf-8'))
    except error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'LLM request failed: {detail or exc.reason}') from exc
    except error.URLError as exc:
        raise RuntimeError(f'LLM request failed: {exc.reason}') from exc

    try:
        return data['choices'][0]['message']['content'].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise RuntimeError('LLM response format was unexpected.') from exc


def stream_dashscope_chat_api(messages):
    req = _build_dashscope_request(messages, stream=True)

    try:
        response = request.urlopen(req, timeout=90)
    except error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'LLM request failed: {detail or exc.reason}') from exc
    except error.URLError as exc:
        raise RuntimeError(f'LLM request failed: {exc.reason}') from exc

    def iterator():
        try:
            for raw_line in response:
                line = raw_line.decode('utf-8', errors='ignore').strip()
                if not line or not line.startswith('data:'):
                    continue

                payload = line[5:].strip()
                if payload == '[DONE]':
                    break

                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                if not chunk.get('choices'):
                    continue

                delta = chunk['choices'][0].get('delta') or {}
                content = delta.get('content') or ''
                if content:
                    yield content
        finally:
            response.close()

    return iterator()


@transaction.atomic
def ensure_product_chat_intro(user, product):
    session = get_or_create_product_chat_session(user, product)
    if session.messages.exists() or session.intro_generated:
        return session

    intro_text = call_dashscope_chat_api(
        build_llm_messages(product, prior_messages=[], intro_mode=True)
    )
    ProductChatMessage.objects.create(
        session=session,
        role=ProductChatMessage.ROLE_ASSISTANT,
        content=intro_text,
    )
    session.intro_generated = True
    session.save(update_fields=['intro_generated', 'updated_at'])
    return session


@transaction.atomic
def append_product_chat_turn(user, product, user_message):
    session = get_or_create_product_chat_session(user, product)
    prior_messages = list(session.messages.all())

    ProductChatMessage.objects.create(
        session=session,
        role=ProductChatMessage.ROLE_USER,
        content=user_message,
    )

    assistant_reply = call_dashscope_chat_api(
        build_llm_messages(product, prior_messages=prior_messages, user_message=user_message)
    )

    ProductChatMessage.objects.create(
        session=session,
        role=ProductChatMessage.ROLE_ASSISTANT,
        content=assistant_reply,
    )
    session.intro_generated = True
    session.save(update_fields=['intro_generated', 'updated_at'])
    return session, assistant_reply


def stream_product_chat_turn(user, product, user_message):
    session = get_or_create_product_chat_session(user, product)
    prior_messages = list(session.messages.all())

    user_record = ProductChatMessage.objects.create(
        session=session,
        role=ProductChatMessage.ROLE_USER,
        content=user_message,
    )

    stream = stream_dashscope_chat_api(
        build_llm_messages(product, prior_messages=prior_messages, user_message=user_message)
    )

    def event_stream():
        assistant_parts = []
        try:
            for chunk in stream:
                assistant_parts.append(chunk)
                yield f'data: {json.dumps({"type": "delta", "content": chunk})}\n\n'

            assistant_text = ''.join(assistant_parts).strip()
            ProductChatMessage.objects.create(
                session=session,
                role=ProductChatMessage.ROLE_ASSISTANT,
                content=assistant_text,
            )
            session.intro_generated = True
            session.save(update_fields=['intro_generated', 'updated_at'])
            yield f'data: {json.dumps({"type": "done"})}\n\n'
        except RuntimeError as exc:
            user_record.delete()
            yield f'data: {json.dumps({"type": "error", "message": str(exc)})}\n\n'
        except Exception:
            user_record.delete()
            yield f'data: {json.dumps({"type": "error", "message": "AI streaming failed unexpectedly."})}\n\n'

    return session, event_stream()


@transaction.atomic
def clear_product_chat_history(user, product):
    session = get_or_create_product_chat_session(user, product)
    session.messages.all().delete()
    session.intro_generated = True
    session.save(update_fields=['intro_generated', 'updated_at'])
    return session
