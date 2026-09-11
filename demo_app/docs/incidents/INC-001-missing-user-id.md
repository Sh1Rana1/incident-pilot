# INC-001：创建用户出现 KeyError

## 现象

不带 `user_id` 调用 `POST /users` 时出现 `KeyError: 'user_id'`，服务返回 500。

## 根因

API 层把未经验证的 payload 直接传给 Service，而 Service 假定 `user_id` 一定存在并使用字典下标读取。

## 正确修复

在 API 边界校验 `user_id` 和 `email`，缺少字段时返回 400。Service 可以保留对已验证输入的明确约束。
