/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 백엔드 주소. 문제 조회 · 채점 · Coding Trace 수집이 전부 여기로 간다. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
