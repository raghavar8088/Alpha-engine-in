import { cn } from '@/lib/utils'

function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('animate-skeleton rounded bg-surface-elevated', className)}
      {...props}
    />
  )
}

export { Skeleton }
