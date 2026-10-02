import styles from './States.module.css'

const WIDTHS = ['92%', '78%', '85%', '64%', '88%', '70%']

// Hueco del panel mientras se genera (lienzo: skeleton con shimmer). Decorativo.
export function Skeleton({ lines = 4 }: { lines?: number }) {
  return (
    <div className={styles.skeleton} aria-hidden="true" data-skeleton="">
      {Array.from({ length: lines }, (_, index) => (
        <span key={index} className={styles.skeletonLine} style={{ width: WIDTHS[index % WIDTHS.length] }} />
      ))}
    </div>
  )
}
