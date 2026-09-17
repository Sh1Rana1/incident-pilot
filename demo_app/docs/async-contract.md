# 用户资料查询契约

`fetch_profile(user_id)` 是异步接口，完成后返回包含 `user_id` 和
`display_name` 的字典。调用方需要等待异步操作完成后再访问结果字段。
`profile_name(user_id)` 对外返回字符串；用户资料存在时应正常返回显示名。
事件循环由应用入口管理，业务函数不能启动嵌套事件循环。
