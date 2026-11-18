import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// 开发/预览/录屏共用同一套配置：
//   端口与后端由环境变量覆盖（VITE_PORT / VITE_API_PORT），默认 25190 → 28020。
//   录屏沙箱用 5182 → 18011，跑的是同一份前端代码，避免出现"录屏版和产品版不一致"。
// 允许通过 Cloudflare 隧道（*.trycloudflare.com）访问，用于把本地演示共享给评委，并支持 sinanlike.com 正式域名。
const TUNNEL_HOSTS = ['sinanlike.com', '.sinanlike.com', '.trycloudflare.com']

export default defineConfig(({ mode }) => {
  const fileEnv = loadEnv(mode, __dirname, '')
  const pick = (key: string, fallback: string) => process.env[key] || fileEnv[key] || fallback

  const devPort = Number(pick('VITE_PORT', '25190'))
  const previewPort = Number(pick('VITE_PREVIEW_PORT', '4180'))
  const backend = pick('VITE_API_PORT', '28020')

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

  /**
   * 公网静态资源缓存：/assets/ 下的文件名带内容哈希，内容变了文件名就变，
   * 所以可以放心让浏览器和 Cloudflare 边缘长期缓存（immutable）。
   * vite preview 默认给所有文件发 `Cache-Control: no-cache`，导致每次打开页面
   * 都要穿过隧道回源到本机校验，这里只覆盖 /assets/，index.html 仍然每次校验。
   */
  const immutableAssets = {
    name: 'tc-immutable-assets',
    configurePreviewServer(server: any) {
      server.middlewares.use((req: any, res: any, next: () => void) => {
        if (req.url && /^\/assets\//.test(req.url)) {
          const setHeader = res.setHeader.bind(res)
          setHeader('Cache-Control', 'public, max-age=31536000, immutable')
          res.setHeader = (k: string, v: any) => (k.toLowerCase() === 'cache-control' ? res : setHeader(k, v))
        }
        next()
      })
    },
  }

  return {
    base: './',
    plugins: [vue(), immutableAssets],
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