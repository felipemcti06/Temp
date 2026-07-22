const STORAGE_KEY = 'chatbot-model-id'

export function getSavedModelId() {
  return localStorage.getItem(STORAGE_KEY)
}

export function saveModelId(modelId) {
  localStorage.setItem(STORAGE_KEY, modelId)
}

export default function ModelSelector({ models, value, onChange, disabled }) {
  const available = models.filter((m) => m.available)

  if (!available.length) {
    return (
      <div className="model-selector model-selector--empty">
        Nenhum modelo de IA configurado no servidor
      </div>
    )
  }

  return (
    <div className="model-selector">
      <label htmlFor="model-select">Modelo</label>
      <select
        id="model-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        {models.map((m) => (
          <option key={m.id} value={m.id} disabled={!m.available}>
            {m.label}
            {!m.available ? ' (indisponível)' : ''}
          </option>
        ))}
      </select>
    </div>
  )
}
