import ReactECharts from "echarts-for-react";

interface TrendChartProps {
  labels: string[];
  series: Array<{ name: string; data: Array<number | null>; type?: "line" | "bar" }>;
}

export function TrendChart({ labels, series }: TrendChartProps) {
  const normalizedSeries = series.map((item) => ({ type: item.type ?? "line", showSymbol: false, connectNulls: true, ...item }));
  return <ReactECharts style={{ height: 360, width: "100%" }} notMerge lazyUpdate option={{ animation: false, tooltip: { trigger: "axis" }, legend: { top: 4 }, grid: { left: 56, right: 24, top: 44, bottom: 44, containLabel: true }, xAxis: { type: "category", data: labels, boundaryGap: false }, yAxis: { type: "value", scale: true }, series: normalizedSeries }} />;
}
