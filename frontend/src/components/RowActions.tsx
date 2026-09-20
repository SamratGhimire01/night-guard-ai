import { ActionIcon, Group, Tooltip } from '@mantine/core'
import { IconPencil, IconTrash } from '@tabler/icons-react'

interface RowActionsProps {
  canWrite: boolean
  onEdit?: () => void
  onDelete?: () => void
}

/** Edit / delete icon buttons for a table row; disabled with an explanatory tooltip for non-owners/admins. */
export default function RowActions({ canWrite, onEdit, onDelete }: RowActionsProps) {
  const buttons = (
    <Group gap={4} justify="flex-end" wrap="nowrap">
      {onEdit && (
        <ActionIcon disabled={!canWrite} onClick={onEdit} aria-label="Edit">
          <IconPencil size={17} stroke={1.75} />
        </ActionIcon>
      )}
      {onDelete && (
        <ActionIcon color="red" disabled={!canWrite} onClick={onDelete} aria-label="Delete">
          <IconTrash size={17} stroke={1.75} />
        </ActionIcon>
      )}
    </Group>
  )
  return canWrite ? buttons : <Tooltip label="Owners and admins only">{buttons}</Tooltip>
}
