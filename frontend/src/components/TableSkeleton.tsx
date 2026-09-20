import { Skeleton, Table } from '@mantine/core'

/** Canonical loading state for a table: header and filters stay put, the body shows placeholder rows. */
export default function TableSkeleton({ cols, rows = 5 }: { cols: number; rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, r) => (
        <Table.Tr key={r}>
          {Array.from({ length: cols }, (_, c) => (
            <Table.Td key={c}>
              <Skeleton height={14} width={c === 0 ? '70%' : '55%'} />
            </Table.Td>
          ))}
        </Table.Tr>
      ))}
    </>
  )
}
