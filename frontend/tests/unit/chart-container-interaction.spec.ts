import { beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import ChartContainer from "../../src/components/ChartContainer.vue";

const chartMock = vi.hoisted(() => {
  const handlers = new Map<string, (params: unknown) => void>();
  const instance = {
    setOption: vi.fn(),
    on: vi.fn((event: string, handler: (params: unknown) => void) => {
      handlers.set(event, handler);
    }),
    off: vi.fn(),
    resize: vi.fn(),
    dispatchAction: vi.fn(),
    convertToPixel: vi.fn(() => [120, 180]),
    containPixel: vi.fn(() => true),
    getOption: vi.fn((): unknown => ({ dataZoom: [] })),
    getWidth: vi.fn(() => 640),
    getHeight: vi.fn(() => 420),
    dispose: vi.fn(),
  };
  return {
    handlers,
    instance,
    init: vi.fn(() => instance),
    use: vi.fn(),
  };
});

vi.mock("echarts/core", () => ({
  init: chartMock.init,
  use: chartMock.use,
}));

describe("ChartContainer interaction bridge", () => {
  beforeEach(() => {
    chartMock.handlers.clear();
    vi.clearAllMocks();
    chartMock.instance.getOption.mockReturnValue({ dataZoom: [] });
  });

  it("forwards chart clicks and exposes generic chart actions", () => {
    const wrapper = mount(ChartContainer, {
      props: { options: {} },
    });
    const clickPayload = {
      seriesId: "stable-series-id",
      dataIndex: 2,
      data: { value: ["2026-01-01T00:00:02Z", 4.2] },
    };

    chartMock.handlers.get("click")?.(clickPayload);
    expect(wrapper.emitted("chartClick")).toEqual([[clickPayload]]);

    const action = { type: "dataZoom", start: 0, end: 100 };
    (wrapper.vm as unknown as { dispatchAction: (payload: typeof action) => void })
      .dispatchAction(action);
    expect(chartMock.instance.dispatchAction).toHaveBeenCalledWith(action);

    const chartApi = wrapper.vm as unknown as {
      convertToPixel: (finder: object, value: unknown) => number[] | null;
      containPixel: (finder: object, value: number[]) => boolean;
      getSize: () => { width: number; height: number };
    };
    expect(chartApi.convertToPixel(
      { xAxisIndex: 0, yAxisIndex: 0 },
      ["2026-01-01T00:00:02Z", 4.2]
    )).toEqual([120, 180]);
    expect(chartMock.instance.convertToPixel).toHaveBeenCalledWith(
      { xAxisIndex: 0, yAxisIndex: 0 },
      ["2026-01-01T00:00:02Z", 4.2]
    );
    expect(chartApi.containPixel({ gridIndex: 0 }, [120, 180])).toBe(true);
    expect(chartApi.getSize()).toEqual({ width: 640, height: 420 });

    wrapper.unmount();
    expect(chartMock.instance.off).toHaveBeenCalledWith("click", expect.any(Function));
    expect(chartMock.instance.off).toHaveBeenCalledWith("datazoom", expect.any(Function));
    expect(chartMock.instance.dispose).toHaveBeenCalledOnce();
  });

  it("emits calculated dataZoom snapshots for direct and batch events", () => {
    const wrapper = mount(ChartContainer, {
      props: { options: {} },
    });
    const calculatedEnd = new Date("2026-01-01T00:10:00Z");

    chartMock.instance.getOption.mockReturnValue({
      dataZoom: [
        {
          id: "inside-zoom",
          xAxisIndex: [0, 0, 2, -1, 1.5, Number.POSITIVE_INFINITY],
          start: 12.5,
          end: 87.5,
          startValue: "2026-01-01T00:00:00Z",
          endValue: calculatedEnd,
        },
        {
          id: "slider-zoom",
          xAxisIndex: 0,
          start: 12.5,
          end: 87.5,
          startValue: 1_767_225_600_000,
          endValue: 1_767_226_200_000,
        },
      ],
    });

    chartMock.handlers.get("datazoom")?.({
      type: "datazoom",
      dataZoomId: "inside-zoom",
      start: 3,
      end: 4,
    });

    expect(wrapper.emitted("chartViewportChange")?.[0]).toEqual([
      {
        reason: "datazoom",
        ranges: [
          {
            dataZoomIndex: 0,
            dataZoomId: "inside-zoom",
            xAxisIndices: [0, 2],
            start: 12.5,
            end: 87.5,
            startValue: "2026-01-01T00:00:00Z",
            endValue: calculatedEnd,
          },
          {
            dataZoomIndex: 1,
            dataZoomId: "slider-zoom",
            xAxisIndices: [0],
            start: 12.5,
            end: 87.5,
            startValue: 1_767_225_600_000,
            endValue: 1_767_226_200_000,
          },
        ],
      },
    ]);

    chartMock.instance.getOption.mockReturnValue({
      dataZoom: [
        null,
        {
          id: 27,
          xAxisIndex: [0, -1, 1.5, Number.NaN, "0"],
          start: Number.NaN,
          end: 70,
          startValue: { epoch: 1_767_225_600_000 },
          endValue: new Date(Number.NaN),
        },
        "malformed",
      ],
    });

    chartMock.handlers.get("datazoom")?.({
      type: "datazoom",
      batch: [{ dataZoomId: "slider-zoom", start: 1, end: 2 }],
    });

    expect(wrapper.emitted("chartViewportChange")?.[1]).toEqual([
      {
        reason: "datazoom",
        ranges: [
          {
            dataZoomIndex: 1,
            xAxisIndices: [0],
            end: 70,
          },
        ],
      },
    ]);
    expect(chartMock.instance.getOption).toHaveBeenCalledTimes(2);

    wrapper.unmount();
  });

  it("emits a resize change without reading or attaching dataZoom ranges", () => {
    const wrapper = mount(ChartContainer, {
      props: { options: {} },
    });

    window.dispatchEvent(new Event("resize"));

    expect(chartMock.instance.resize).toHaveBeenCalledOnce();
    expect(chartMock.instance.getOption).not.toHaveBeenCalled();
    expect(wrapper.emitted("chartViewportChange")).toEqual([
      [{ reason: "resize" }],
    ]);

    wrapper.unmount();
  });
});
