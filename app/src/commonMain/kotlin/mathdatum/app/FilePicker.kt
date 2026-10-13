package mathdatum.app

import androidx.compose.runtime.Composable

/**
 * Возвращает действие «выбрать текстовый файл»: после выбора вызывает [onPicked] с именем и содержимым (UTF-8).
 * Реализации: desktop — системный диалог, Android — системный выбор документа, web — скрытое поле выбора файла.
 */
@Composable
expect fun rememberTextFilePicker(onPicked: (name: String, text: String) -> Unit): () -> Unit
