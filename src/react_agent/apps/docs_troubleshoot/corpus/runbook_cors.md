# 浏览器跨域（CORS）

浏览器跨域调用 API 前会发送 **OPTIONS** 预检（preflight）。服务端须在响应中包含：

```
Access-Control-Allow-Origin: <allowed-origin>
```

允许源通过环境变量 **`REACT_AGENT_CORS_ORIGINS`** 配置（逗号分隔）。未配置时默认仅允许同源。
