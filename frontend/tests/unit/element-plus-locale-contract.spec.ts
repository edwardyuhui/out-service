import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Element Plus locale contract", () => {
  it("registers the official simplified-Chinese locale globally", () => {
    const mainSource = readFileSync(resolve(process.cwd(), "src/main.ts"), "utf8");

    expect(mainSource).toContain(
      'import zhCn from "element-plus/es/locale/lang/zh-cn";'
    );
    expect(mainSource).toContain("app.use(ElementPlus, { locale: zhCn });");
  });
});
