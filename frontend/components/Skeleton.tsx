export default function Skeleton({ height = 16, width = "100%", radius = 8, style }: { height?: number; width?: string | number; radius?: number; style?: React.CSSProperties }) {
  return <div className="skeleton" style={{ height, width, borderRadius: radius, ...style }} />;
}
