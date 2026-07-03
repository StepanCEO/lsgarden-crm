# Интеграция WordPress -> CRM

CRM принимает данные сайта через webhook:

- URL: `/api/site/webhook/`
- Метод: `POST`
- Авторизация: заголовок `X-CRM-Token: <SITE_WEBHOOK_TOKEN>`
- Формат: `application/json`

Полный URL на проде:

```text
https://crm.lsgarden.ru/api/site/webhook/
```

## Заказ с сайта

```json
{
  "type": "order",
  "submission_id": "wp-order-1001",
  "name": "Мария Сергеевна",
  "phone": "+7 (999) 123-45-67",
  "email": "maria@example.com",
  "items": [
    {"name": "Фикус Лирата", "qty": 2, "price": 3500},
    {"name": "Монстера", "qty": 1, "price": 4200}
  ],
  "wishlist": ["Орхидея Фаленопсис"],
  "comment": "Нужна доставка после 18:00"
}
```

Что делает CRM:

- создаёт или обновляет клиента по телефону/email
- создаёт заказ
- записывает wishlist в карточку клиента
- игнорирует повтор, если уже приходил такой `submission_id`

## Wishlist с сайта

```json
{
  "type": "wishlist",
  "submission_id": "wp-wishlist-7",
  "email": "lead@example.com",
  "nomenclature": ["Сансевиерия", "Фиттония"]
}
```

Что делает CRM:

- создаёт или обновляет клиента
- добавляет позиции в `wish_list`
- игнорирует повтор, если уже приходил такой `submission_id`

## Что поставить на WordPress

Подойдёт любой способ, который умеет отправлять POST-запрос на внешний URL:

- WP Webhooks
- Uncanny Automator
- кастомный `wp_remote_post(...)` в теме или плагине

Минимальный пример для WordPress:

```php
$payload = [
    'type' => 'wishlist',
    'submission_id' => 'wp-wishlist-7',
    'email' => 'lead@example.com',
    'nomenclature' => ['Сансевиерия', 'Фиттония'],
];

wp_remote_post('https://crm.lsgarden.ru/api/site/webhook/', [
    'headers' => [
        'Content-Type' => 'application/json',
        'X-CRM-Token' => 'YOUR_SITE_WEBHOOK_TOKEN',
    ],
    'body' => wp_json_encode($payload),
    'timeout' => 15,
]);
```
