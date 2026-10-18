import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import ru.gsisoft.common.math.di.MathModule;
import ru.gsisoft.common.math.localization.model.LocalizationData;
import ru.gsisoft.common.math.localization.model.MathResult;
import ru.gsisoft.common.model.objects.coordinate.Coordinate;

/**
 * Изолированная проверка решателя: getGSKOLocalization и getPlaneLocalization
 * на уже спроецированных координатах (N, E, h) → (x, y, H). Модель ГСКО совпадает
 * с эталонным подобием, поэтому невязки должны совпасть с эталоном МНК.
 *
 * Выход: ISO GSKO|PLANE rms_м | ISO ERROR ...
 */
public class GskoCheck {
    public static void main(String[] args) throws Exception {
        Map<String, List<Coordinate[]>> regions = new LinkedHashMap<>();
        for (String line : Files.readAllLines(Path.of(args[0]))) {
            String[] s = line.trim().split("\\s+");
            if (s.length < 8 || !s[1].equals("C")) continue;
            double[] v = new double[6];
            for (int i = 0; i < 6; i++) v[i] = Double.parseDouble(s[2 + i]);
            regions.computeIfAbsent(s[0], k -> new ArrayList<>())
                .add(new Coordinate[]{new Coordinate(v[0], v[1], v[2]), new Coordinate(v[3], v[4], v[5])});
        }
        var repo = MathModule.INSTANCE.getLocalizationRepository();
        for (var e : regions.entrySet()) {
            List<Coordinate> from = new ArrayList<>(), to = new ArrayList<>();
            for (Coordinate[] p : e.getValue()) { from.add(p[0]); to.add(p[1]); }
            try {
                var g = repo.getGSKOLocalization(from, to);
                var h = repo.getPlaneLocalization(from, to);
                System.out.println(e.getKey() + " GSKO " + rms(g, true));
                System.out.println(e.getKey() + " PLANE " + rms(h, false));
            } catch (Throwable ex) {
                System.out.println(e.getKey() + " ERROR " + ex);
            }
        }
    }

    static String rms(MathResult<?, ?> r, boolean plan) {
        if (!(r instanceof MathResult.Success<?> s)) return "ERROR";
        LocalizationData d = (LocalizationData) s.getValue();
        double sum = 0;
        int n = d.getFunResidualLat().size();
        for (int i = 0; i < n; i++) {
            if (plan) {
                double a = Double.parseDouble(d.getFunResidualLat().get(i)), b = Double.parseDouble(d.getFunResidualLon().get(i));
                sum += a * a + b * b;
            } else {
                double c = Double.parseDouble(d.getFunResidualH().get(i));
                sum += c * c;
            }
        }
        return String.valueOf(Math.sqrt(sum / n));
    }
}
