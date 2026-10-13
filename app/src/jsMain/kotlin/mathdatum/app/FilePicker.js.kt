package mathdatum.app

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import kotlinx.browser.document
import org.w3c.dom.HTMLInputElement
import org.w3c.files.FileReader

@Composable
actual fun rememberTextFilePicker(onPicked: (name: String, text: String) -> Unit): () -> Unit {
    val current by rememberUpdatedState(onPicked)
    return remember {
        {
            // скрытое поле в документе: так диалог открывается и при повторных вызовах
            val input = document.createElement("input") as HTMLInputElement
            input.type = "file"
            input.style.display = "none"
            document.body?.appendChild(input)
            fun cleanup() { input.parentNode?.removeChild(input) }
            input.onchange = {
                val file = input.files?.item(0)
                if (file != null) {
                    val reader = FileReader()
                    reader.onload = { current(file.name, reader.result?.toString() ?: ""); cleanup() }
                    reader.onerror = { cleanup() }
                    reader.readAsText(file)
                } else cleanup()
                null
            }
            input.addEventListener("cancel", { cleanup() })
            input.click()
        }
    }
}
