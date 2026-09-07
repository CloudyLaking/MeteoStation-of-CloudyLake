import unittest
from datetime import datetime, timezone
import numpy as np
import xarray as xr

from meteostation.weather_map.fields import WeatherGrid
from meteostation.weather_map.models import WeatherMapDomain
from meteostation.weather_map.regions import region_domain
from meteostation.weather_map.presentation import filtered, colour_recipe, signal_notes, closed_centres
from meteostation.weather_map.decode import find_data_values, STANDARD_GRAVITY_MS2
from meteostation.weather_map.cyclones import parse_jtwc_bdeck

NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)
CHINA = WeatherMapDomain(west=70,east=145,south=15,north=60,resolution_degrees=.25,projection='plate-carree')


class WeatherPresentationTests(unittest.TestCase):
    def test_dateline_subset_keeps_field_and_coordinate_order(self):
        lon=np.arange(360);lat=np.arange(-80,81)
        g=WeatherGrid(NOW,'test',lon,lat,{'x':np.tile(lon,(len(lat),1))})
        world=g.subset(region_domain('world',None,CHINA))
        self.assertEqual(world.longitude[0],-180)
        np.testing.assert_array_equal(world.fields['x'][0],world.longitude%360)
        pacific=g.subset(region_domain('pacific',[150,-30,210,30],CHINA))
        self.assertEqual(pacific.longitude[-1],210)
        with self.assertRaises(ValueError): g.subset(CHINA).subset(region_domain('world',None,CHINA))

    def test_region_input_is_bounded_and_cannot_overwrite_china(self):
        for name,bounds in [('china',[80,20,120,40]),('../escape',[80,20,120,40]),('world',[0,0,10,10]),('tiny',[80,20,81,21]),('bad',[80,20,float('nan'),40])]:
            with self.subTest(name=name),self.assertRaises(ValueError):region_domain(name,bounds,CHINA)

    def test_smoothing_never_refills_underground_temperature(self):
        sp=np.full((21,21),1000.);sp[8:13,8:13]=700
        t=np.full((21,21),20.);t[8:13,8:13]=100
        g=WeatherGrid(NOW,'test',np.arange(21),np.arange(21),{'temperature_850_c':t,'surface_pressure_hpa':sp})
        result=filtered(g,'temperature_850_c',850)
        self.assertTrue(np.isnan(result[8:13,8:13]).all())
        np.testing.assert_allclose(result[np.isfinite(result)],20)

    def test_missing_climatology_never_becomes_an_anomaly(self):
        values=np.full((3,3),15.)
        g=WeatherGrid(NOW,'test',np.arange(3),np.arange(3),{'temperature_850_c':values})
        self.assertNotIn('anomaly',colour_recipe(g,'composite')[3])

    def test_precipitation_readout_is_mm_not_temperature(self):
        values=np.array([[0.,5.],[10.,50.]])
        g=WeatherGrid(NOW,'test',np.arange(2),np.arange(2),{'precipitation_accumulation_mm':values}, {'precipitation':{'hours':12}})
        recipe=colour_recipe(g,'surface')
        self.assertIn('12-h',recipe[3]);self.assertIn('mm',recipe[3])
        self.assertIn('50.0 mm',signal_notes(g,'surface',recipe[0])[0])
        self.assertNotIn('°C',signal_notes(g,'surface',recipe[0])[0])

    def test_closed_centres_work_in_southern_hemisphere(self):
        lon=np.arange(41);lat=np.arange(-60,-19);xx,yy=np.meshgrid(lon,lat)
        values=1030-35*np.exp(-((xx-20)**2+(yy+40)**2)/30)
        g=WeatherGrid(NOW,'test',lon,lat,{'mslp_hpa':values,'surface_pressure_hpa':np.full_like(values,1000)})
        domain=region_domain('south',[0,-60,40,-20],CHINA)
        centres=closed_centres(g,domain)
        self.assertTrue(any(m.kind=='low-pressure' and abs(m.latitude+40)<2 for m in centres))

    def test_grib_pressure_selection_must_match_exactly_and_z_uses_units(self):
        z=xr.DataArray(np.full((1,2,2),1500*STANDARD_GRAVITY_MS2),dims=('isobaricInhPa','latitude','longitude'),coords={'isobaricInhPa':[850],'latitude':[0,1],'longitude':[0,1]})
        dataset=xr.Dataset({'z':z})
        np.testing.assert_allclose(find_data_values([dataset],aliases=('z',),pressure_hpa=850),1500)
        self.assertIsNone(find_data_values([dataset],aliases=('z',),pressure_hpa=500))

    def test_multibasin_storms_keep_knots_and_reject_future_analysis(self):
        for basin,lon,suffix,agency in [('AL','600W','L','NHC'),('SH','1700W','P','JTWC'),('WP','1300E','W','JTWC')]:
            row=[basin,'01','2026090600','','BEST','0','200N',lon,'65','980']+['']*17+['TEST']
            marker=parse_jtwc_bdeck(','.join(row),valid_at=NOW,source_url='https://example.invalid')
            self.assertEqual(marker.id,'01'+suffix);self.assertEqual(marker.maximum_wind_kt,65)
            self.assertIn(agency,marker.source)
            row[2]='2026090606'
            self.assertIsNone(parse_jtwc_bdeck(','.join(row),valid_at=NOW,source_url='https://example.invalid'))


if __name__=='__main__':unittest.main()
