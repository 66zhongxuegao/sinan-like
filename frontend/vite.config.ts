import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// 开发/预览/录屏共用同一套配置：
//   端口与后端由环境变量覆盖（VITE_PORT / VITE_API_PORT），默认 5190 → 18020。
//   录屏沙箱用 5182 → 18011，跑的是同一份前端代码，避免出现"录屏版和产品版不一致"。
// 允许通过 Cloudflare 隧道（*.trycloudflare.com）访问，用于把本地演示共享给评委。
const TUNNEL_HOSTS = ['.trycloudflare.com']

export default defineConfig(({ mode }) => {
  const fileEnv = loadEnv(mode, __dirname, '')
  const pick = (key: string, fallback: string) => process.env[key] || fileEnv[key] || fallback

  const devPort = Number(pick('VITE_PORT', '5190'))
  const previewPort = Number(pick('VITE_PREVIEW_PORT', '4180'))
  const backend = pick('VITE_API_PORT', '18020')

  const apiProxy = {
    '/api': {
      target: `http://127.0.0.1:${backend}`,
      changeOrigin: true,
      ws: true,
      rewrite: (p: string) => p.replace(/^\/api/, ''),
      timeout: 300000,
      proxyTimeout: 300000,
    },
  }

  return {
    base: './',
    plugins: [vue()],
    resolve: {
      alias: { '@': resolve(__dirname, 'src') },
    },
    server: {
      port: devPort,
      strictPort: true,
      allowedHosts: TUNNEL_HOSTS,
      proxy: apiProxy,
    },
    preview: {
      port: previewPort,
      allowedHosts: TUNNEL_HOSTS,
      proxy: apiProxy,
    },
  }
})