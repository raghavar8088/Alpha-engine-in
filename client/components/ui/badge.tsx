import { cn } from '@/lib/utils'

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'default' | 'profit' | 'loss' | 'warning' | 'muted'
}

export function Badge({ className, variant = 'default', ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
        {
          'bg-primary/15 text-primary': variant === 'default',
          'bg-profit-green/15 text-profit-green': variant === 'profit',
          'bg-loss-red/15 text-loss-red': variant === 'loss',
          'bg-neutral-yellow/15 text-neutral-yellow': variant === 'warning',
          'bg-text-muted/15 text-text-secondary': variant === 'muted',
        },
        className
      )}
      {...props}
    />
  )
}
