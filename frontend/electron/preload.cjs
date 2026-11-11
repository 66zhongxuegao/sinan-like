// 预加载脚本：暂时只暴露一个版本号，后续要给桌面端加能力（导出 PDF、打开本地文件）再往下放。
const { contextBridge } = require('electron')
contextBridge.exposeInMainWorld('tripcraft', { desktop: true, version: '0.1.0' })
