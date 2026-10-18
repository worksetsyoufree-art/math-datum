import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import ru.gsisoft.common.math.di.MathModule;
import ru.gsisoft.common.math.localization.LocalizationRepository;
import ru.gsisoft.common.math.localization.model.LocalizationData;
import ru.gsisoft.common.math.localization.model.MathResult;
import ru.gsisoft.common.math.localization.model.ResLocalization;
import ru.gsisoft.common.model.cs.Datum;
import ru.gsisoft.common.model.objects.coordinate.Coordinate;

/**
 * Прогоняет локализацию gsimath (LocalizationRepository.getLocalization, как в
 * LocalizationPairsImpl.calculate) на точках из data/geodetic и печатает результат.
 *
 * Вход: строки "ISO C|K B L h x y H"; второй аргумент (необязательный) — сколько опорных точек брать. Выход (stdout): строки
 *   ISO STATUS kind idx resLat resLon resH predActX predActY predActH predTwoX predTwoY predTwoH
 * где predAct — CommonMathRepository.calculateToActualCoordinate (путь приложения),
 * predTwo — TransformCoordinateRepository.getTransformationTwoDatums(WGS → датум локализации).
 */
public class LocalizationCheck {
    record Pt(String kind, Coordinate wgs, Coordinate local) {}

    public static void main(String[] args) throws Exception {
        Map<String, List<Pt>> regions = new LinkedHashMap<>();
        for (String line : Files.readAllLines(Path.of(args[0]))) {
            String[] s = line.trim().split("\\s+");
            if (s.length < 8) continue;
            double[] v = new double[6];
            for (int i = 0; i < 6; i++) v[i] = Double.parseDouble(s[2 + i]);
            regions.computeIfAbsent(s[0], k -> new ArrayList<>())
                .add(new Pt(s[1], new Coordinate(v[0], v[1], v[2]), new Coordinate(v[3], v[4], v[5])));
        }
        int maxCtrl = args.length > 1 ? Integer.parseInt(args[1]) : Integer.MAX_VALUE;
        for (var pts : regions.values()) {
            int[] n = {0};
            pts.removeIf(p -> p.kind.equals("C") && ++n[0] > maxCtrl);
        }
        LocalizationRepository repo = MathModule.INSTANCE.getLocalizationRepository();
        var common = MathModule.INSTANCE.getCommonMathRepository();
        var transform = MathModule.INSTANCE.getTransformCoordinateRepository();
        Datum wgs = Datum.Companion.getWGS84();

        for (var e : regions.entrySet()) {
            String iso = e.getKey();
            List<Coordinate> from = new ArrayList<>(), to = new ArrayList<>();
            for (Pt p : e.getValue()) if (p.kind.equals("C")) { from.add(p.wgs); to.add(p.local); }
            long t0 = System.nanoTime();
            try {
                ResLocalization res = repo.getLocalization(from, to, from, to, wgs);
                double ms = (System.nanoTime() - t0) / 1e6;
                if (!(res.getResInPlane() instanceof MathResult.Success<?> plane)
                    || !(res.getResInHight() instanceof MathResult.Success<?> height)) {
                    System.out.println(iso + " ERROR plane=" + res.getResInPlane().getClass().getSimpleName()
                        + " height=" + res.getResInHight().getClass().getSimpleName());
                    continue;
                }
                LocalizationData pd = (LocalizationData) plane.getValue();
                LocalizationData hd = (LocalizationData) height.getValue();
                Datum d = res.getDatumProj();
                // Как в LocalizationPairsImpl: datumProj + ГСКО из плана + ВСКО из высот, isFromLocalization = true.
                Datum loc = d.copy(d.getAzimuth(), d.getOrientation(), d.getCountry(), "Локализация",
                    d.getEllipsoidOriginal(), d.getEllipsoid(), d.getProjectionOrNull(), d.getParameters7OrNull(),
                    pd.getParams().getGSKOIfUsed(), hd.getParams().getVSKOIfUsed(),
                    d.isPredefined(), d.isLocal(), d.getRtcmData(), d.getGeoid(), true);
                Datum locNoFlag = loc.copy(loc.getAzimuth(), loc.getOrientation(), loc.getCountry(), loc.getCsCode(),
                    loc.getEllipsoidOriginal(), loc.getEllipsoid(), loc.getProjectionOrNull(), loc.getParameters7OrNull(),
                    loc.getParamGSKOOrNull(), loc.getParamVSKOOrNull(),
                    loc.isPredefined(), loc.isLocal(), loc.getRtcmData(), loc.getGeoid(), false);
                System.out.println(iso + " INFO ms=" + String.format(Locale.ROOT, "%.1f", ms) + " datum=" + loc);
                int ic = 0;
                for (Pt p : e.getValue()) {
                    String rl = "nan", ro = "nan", rh = "nan";
                    if (p.kind.equals("C")) {
                        rl = pd.getFunResidualLat().get(ic);
                        ro = pd.getFunResidualLon().get(ic);
                        rh = hd.getFunResidualH().get(ic);
                        ic++;
                    }
                    Coordinate a = common.calculateToActualCoordinate(p.wgs, loc, null);
                    Coordinate b = transform.getTransformationTwoDatums(p.wgs, Datum.Companion.getNull(), locNoFlag);
                    System.out.println(String.format(Locale.ROOT, "%s OK %s %s %s %s %.6f %.6f %.6f %.6f %.6f %.6f",
                        iso, p.kind, rl, ro, rh, a.getLatBN(), a.getLonLE(), a.getAltHZ(), b.getLatBN(), b.getLonLE(), b.getAltHZ()));
                }
            } catch (Throwable ex) {
                System.out.println(iso + " EXCEPTION " + ex);
            }
        }
    }
}
