/**
 * MacroChipRow.tsx — 5-way single-select chip toggle (Calories/Protein/Carbs/Fat/Fiber).
 *
 * Each chip's ACTIVE state uses its OWN metric color — the indigo-500 tab
 * highlight used elsewhere in the hub is intentionally never reused here, per
 * the 30-UI-SPEC Color § reserved-highlight-color carve-out: that shared
 * highlight is explicitly NOT used for chart series/lines, modality badges,
 * macro chip active states, or any nutrition value. Inactive chips use
 * `border` background + textSecondary text (30-UI-SPEC Component Inventory §
 * MacroChipRow).
 *
 * Default selection is Calories (D-14) — the parent (NutritionDetailPage)
 * owns the selected metric; this component is fully controlled.
 *
 * Scrolls horizontally on narrow phones (overflow-x auto, flex-shrink 0 per
 * chip) — 30-UI-SPEC Responsive § Nutrition page.
 */
import { border, textSecondary, typography, fontFamily } from '../../../tokens'
import type { NutritionMacroKey } from '../../../api/health'

/** Metric → color map (30-UI-SPEC Color § New color additions — Nutrition macro series). */
export const MACRO_COLORS: Record<NutritionMacroKey, string> = {
  calories: '#38BDF8',
  protein_g: '#F87171',
  carbs_g: '#FBBF24',
  fat_g: '#A78BFA',
  fiber_g: '#2DD4BF',
}

/** Metric → display label (30-UI-SPEC Copywriting § Nutrition Detail page). */
export const MACRO_LABELS: Record<NutritionMacroKey, string> = {
  calories: 'Calories',
  protein_g: 'Protein',
  carbs_g: 'Carbs',
  fat_g: 'Fat',
  fiber_g: 'Fiber',
}

const MACRO_ORDER: NutritionMacroKey[] = ['calories', 'protein_g', 'carbs_g', 'fat_g', 'fiber_g']

interface MacroChipRowProps {
  /** Selected metric — controlled by the parent. */
  metric: NutritionMacroKey
  onChange: (metric: NutritionMacroKey) => void
}

export function MacroChipRow({ metric, onChange }: MacroChipRowProps) {
  return (
    <div
      role="group"
      aria-label="Macro selector"
      style={{
        display: 'flex',
        gap: '8px',
        overflowX: 'auto',
        WebkitOverflowScrolling: 'touch',
        paddingBottom: '2px',
      }}
    >
      {MACRO_ORDER.map((key) => {
        const active = key === metric
        const color = MACRO_COLORS[key]
        return (
          <button
            key={key}
            type="button"
            onClick={() => onChange(key)}
            aria-pressed={active}
            style={{
              flexShrink: 0,
              minWidth: '44px', // touch target width
              height: '32px',
              padding: '0 14px',
              borderRadius: '8px',
              border: `1px solid ${active ? color : border}`,
              backgroundColor: active ? color : border,
              color: active ? '#0A0A0A' : textSecondary,
              fontSize: typography.label.fontSize,
              fontWeight: active ? 600 : 400,
              fontFamily,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              transition: 'background-color 0.15s, color 0.15s',
            }}
          >
            {MACRO_LABELS[key]}
          </button>
        )
      })}
    </div>
  )
}
