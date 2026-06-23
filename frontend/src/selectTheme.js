/** Dark theme for react-select — matches landing / app shell */
export const darkSelectStyles = {
  control: (base, state) => ({
    ...base,
    backgroundColor: 'rgba(17, 24, 39, 0.85)',
    borderColor: state.isFocused ? 'rgba(20, 184, 166, 0.5)' : 'rgba(255, 255, 255, 0.12)',
    boxShadow: state.isFocused ? '0 0 0 2px rgba(20, 184, 166, 0.2)' : 'none',
    borderRadius: '0.5rem',
    minHeight: '42px',
    '&:hover': { borderColor: 'rgba(255, 255, 255, 0.2)' },
  }),
  menu: (base) => ({
    ...base,
    backgroundColor: 'rgb(17, 24, 39)',
    border: '1px solid rgba(255, 255, 255, 0.12)',
    borderRadius: '0.5rem',
    overflow: 'hidden',
    zIndex: 50,
  }),
  menuList: (base) => ({
    ...base,
    padding: '4px',
  }),
  option: (base, state) => ({
    ...base,
    backgroundColor: state.isSelected
      ? 'rgba(20, 184, 166, 0.22)'
      : state.isFocused
        ? 'rgba(255, 255, 255, 0.08)'
        : 'transparent',
    color: state.isSelected ? '#5eead4' : '#e5e7eb',
    cursor: 'pointer',
    borderRadius: '0.375rem',
  }),
  singleValue: (base) => ({
    ...base,
    color: '#f3f4f6',
  }),
  multiValue: (base) => ({
    ...base,
    backgroundColor: 'rgba(20, 184, 166, 0.15)',
    borderRadius: '0.375rem',
  }),
  multiValueLabel: (base) => ({
    ...base,
    color: '#99f6e4',
  }),
  multiValueRemove: (base) => ({
    ...base,
    color: '#5eead4',
    '&:hover': {
      backgroundColor: 'rgba(239, 68, 68, 0.3)',
      color: '#fca5a5',
    },
  }),
  input: (base) => ({
    ...base,
    color: '#f3f4f6',
  }),
  placeholder: (base) => ({
    ...base,
    color: '#6b7280',
  }),
  indicatorSeparator: (base) => ({
    ...base,
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
  }),
  dropdownIndicator: (base) => ({
    ...base,
    color: '#9ca3af',
    '&:hover': { color: '#d1d5db' },
  }),
  clearIndicator: (base) => ({
    ...base,
    color: '#9ca3af',
    '&:hover': { color: '#d1d5db' },
  }),
  groupHeading: (base) => ({
    ...base,
    color: '#14b8a6',
    fontSize: '0.7rem',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  }),
  noOptionsMessage: (base) => ({
    ...base,
    color: '#9ca3af',
  }),
}
