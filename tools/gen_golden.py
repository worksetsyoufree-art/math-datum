import pyproj
pts=[(55.75,37.62,150.0),(60.0,30.3,10.0),(43.1,131.9,0.0),(69.0,33.0,500.0),(-33.9,151.2,20.0),(55.0,45.0,0.0)]
P=pyproj.Transformer.from_pipeline("+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step +proj=cart +ellps=WGS84 +step +proj=helmert +x=23.92 +y=-141.27 +z=-80.9 +rx=0 +ry=-0.35 +rz=-0.82 +s=-0.12 +convention=coordinate_frame +exact +step +inv +proj=cart +ellps=krass +step +proj=tmerc +lat_0=0 +lon_0=39 +k=1 +x_0=7500000 +y_0=0 +ellps=krass")
for la,lo,h in pts:
    e,n,hh=P.transform(lo,la,h); print(f"G({la}, {lo}, {h}, {n!r}, {e!r}, {hh!r}),")
print('UTM')
U=pyproj.Transformer.from_crs(4326,32637,always_xy=True)
for la,lo in [(55.75,37.62),(60.0,30.3),(0.0,36.0),(-33.9,39.5)]:
    e,n=U.transform(lo,la); print(f"U({la}, {lo}, {n!r}, {e!r}),")
