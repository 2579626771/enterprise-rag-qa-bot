import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
// 开发服务器配置。
// proxy：把前端发往 /api 的请求，转发到后端 FastAPI(默认 8000 端口)。
// 好处：前端代码里统一写 /api/xxx，既不用写死后端地址，生产环境也不必依赖 CORS。
export default defineConfig({
    plugins: [vue()],
    server: {
        // host: true 让开发服务器监听 0.0.0.0，同一局域网内的其他设备可通过
        // http://<本机IP>:5173 访问。仅本机访问时用 localhost 依然有效。
        host: true,
        port: 5173,
        proxy: {
            '/api': {
                // 浏览器只跟前端(5173)通信，前端再把 /api 转发到本机后端(8000)。
                // 因此后端无需对外暴露，局域网用户也不用改后端地址。
                target: 'http://127.0.0.1:8000',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api/, ''),
            },
        },
    },
});
