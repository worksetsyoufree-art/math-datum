package mathdatum.app

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import java.awt.FileDialog
import java.awt.Frame
import java.io.File

@Composable
actual fun rememberTextFilePicker(onPicked: (name: String, text: String) -> Unit): () -> Unit {
    val current by rememberUpdatedState(onPicked)
    return remember {
        {
            val dialog = FileDialog(null as Frame?, "Открыть файл", FileDialog.LOAD)
            dialog.isVisible = true
            val file = dialog.file
            if (file != null) {
                val f = File(dialog.directory, file)
                current(f.name, f.readText(Charsets.UTF_8))
            }
        }
    }
}
