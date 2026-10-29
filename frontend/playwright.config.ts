import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: {
    baseURL: "http://127.0.0.1:5174",
    headless: true,
    viewport: { width: 1440, height: 1050 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    launchOptions: {
      args: [
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
      ],
    },
  },
  webServer: [
    {
      command:
        "../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8766",
      url: "http://127.0.0.1:8766/api/topics",
      reuseExistingServer: false,
      env: {
        SPEAKLAB_DATA_DIR: "./data/e2e",
        SPEAKLAB_OLLAMA_URL: "http://127.0.0.1:1",
        SPEAKLAB_WHISPER_URL: "http://127.0.0.1:1",
        SPEAKLAB_MODEL_TIMEOUT: "2",
      },
    },
    {
      command: "npm run dev -- --port 5174",
      url: "http://127.0.0.1:5174",
      reuseExistingServer: false,
      env: { SPEAKLAB_API_TARGET: "http://127.0.0.1:8766" },
    },
  ],
});
