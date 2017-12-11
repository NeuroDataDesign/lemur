import sys, os
import boto3
import botocore
from flask import Flask, session, render_template, request, send_from_directory, url_for, redirect
import logging
from logging.handlers import RotatingFileHandler
import json

#sys.path.append(os.path.abspath(os.path.join('..')))
from lemur import datasets as lds, metrics as lms, plotters as lpl, embedders as leb

app = Flask(__name__)

app.debug = True

app.secret_key = 'A0Zr98j/3yX R~XHH!jmN]LWX/,?RT'

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

MEDA_options = [
    #'NameOfPlotInLemur': 'name-of-plot-file-name'
    ('Heatmap', 'Heatmap', 'heatmap'),
    ('Histogram Heatmap', 'HistogramHeatmap', 'histogramheatmap'),
    ('Location Lines', 'LocationLines', 'locationlines'),
    ('Location Heatmap', 'LocationHeatmap', 'locationheatmap'),
    ('Scree Plot', 'ScreePlotter', 'screeplot'),
]

MEDA_Embedded_options = [
    ('Heatmap', 'Heatmap', 'embheatmap'),
    ('Histogram Heatmap', 'HistogramHeatmap', 'embhistogramheatmap'),
    ('Location Lines', 'LocationLines', 'emblocationlines'),
    ('Location Heatmap', 'LocationHeatmap', 'emblocationheatmap'),
    ('Scree Plot', 'ScreePlotter', 'embscreeplot'),
    ('Correlation Matrix', 'CorrelationMatrix', 'embcorr'),
    ('Eigenvector Heatmap', 'EigenvectorHeatmap', 'embevheat'),
    ('HGMM Stacked Cluster Means Heatmap', 
     'HGMMStackedClusterMeansHeatmap',
     'hgmmstackedclustermeansheatmap'),
    ('HGMM Cluster Means Dendrogram',
     'HGMMClusterMeansDendrogram',
     'hgmmclustermeansdendrogram'),
    ('HGMM Pairs Plot',
     'HGMMPairsPlot',
      'hgmmpairsplot'),
    ('HGMM Cluster Means Level Lines',
     'HGMMClusterMeansLevelLines',
      'hgmmclustermeanslevellines'),
    ('HGMM Cluster Means Level Heatmap',
     'HGMMClusterMeansLevelHeatmap',
     'hgmmclustermeanslevelheatmap'),
]

@app.route('/')
def index():
    return redirect(url_for('medahome'))

@app.route('/MEDA/home')
def medahome():
    basedir = os.path.join(APP_ROOT, 'data')
    datasets = os.listdir(basedir)
    metas = []
    for d in datasets:
        with open(os.path.join(basedir, d, "metadata.json")) as f:
            rawjson = f.read()
        metadata = json.loads(rawjson)
        metas.append(metadata)
    return render_template('home.html', metas = metas)

@app.route('/MEDA/upload')
def uploadrender():
    return render_template("upload.html")

@app.route('/MEDA/<ds_name>/<plot_name>')
def meda(ds_name=None, plot_name=None):
    app.logger.info('DS Name is: %s', ds_name)
    app.logger.info('Plot Name is: %s', plot_name)

    base_path = os.path.join(APP_ROOT, 'data', ds_name)

    if plot_name == "default":
        todisp = "<h1> Choose a plot! </h1>"
    elif plot_name is not None:
        plot_filename = "%s.html"%(plot_name)
        plot_path = os.path.join(base_path, plot_filename)
        with open(plot_path, "r") as f:
            todisp = f.read()
    else:
        todisp = "<h1> Choose a plot! </h1>"
    return render_template('meda.html',
                           plot=todisp,
                           MEDA_options=MEDA_options,
                           MEDA_Embedded_options=MEDA_Embedded_options)


@app.route('/upload', methods=['POST'])
def upload():
    target = os.path.join(APP_ROOT,'data')
    app.logger.info('Target route: %s', target)

    file = request.files.getlist("file")[0]
    filename = file.filename
    filedir = "".join(filename.split(".")[:-1])
    dspath = os.path.join(target, filedir)
    os.makedirs(dspath, exist_ok=True)
    session['basepath'] = dspath

    destination = os.path.join(dspath, filename)
    app.logger.info('Accept incoming file: %s', filename)
    app.logger.info('Save it to: %s', destination)
    file.save(destination)
    session['data'] = destination

    # Create the dataset object
    csv_ds = lds.CSVDataSet(session['data'], name = filedir)


    # Clean the dataset object
    csv_ds.imputeColumns("mean")

    # Save metadata
    csv_ds.saveMetaData(os.path.join(dspath, "metadata.json"))

    # Create a lemur distance matrix based on the EEG data
    DM = lds.DistanceMatrix(csv_ds, lms.VectorDifferenceNorm)

    # Compute an embedding for the more intensive plots        
    MDSEmbedder = leb.MDSEmbedder(num_components=3)
    csv_embedded = MDSEmbedder.embed(DM)
    for _, lemurname, plotname in MEDA_options:
        tosave = getattr(lpl, lemurname)(csv_ds, mode='div').plot()
        plotfilename = "%s.html"%(plotname)
        plotpath = os.path.join(dspath, plotfilename)
        with open(plotpath, "w") as f:
            app.logger.info('Writing to file: %s', plotfilename)
            f.write(tosave)
            f.close()

    for _, lemurname, plotname in MEDA_Embedded_options:
        tosave = getattr(lpl, lemurname)(csv_embedded, mode='div').plot()
        plotfilename = "%s.html"%(plotname)
        plotpath = os.path.join(dspath, plotfilename)
        with open(plotpath, "w") as f:
            app.logger.info('Writing to file: %s', plotfilename)
            f.write(tosave)
            f.close()
    return redirect(url_for('meda', ds_name=filedir, plot_name='default'))

@app.route('/s3upload', methods=['POST'])
def s3upload():
    target = os.path.join(APP_ROOT,'text')
    app.logger.info('Target route: %s', target)

    if not os.path.isdir(target):
        os.mkdir(target)

    for file in request.files.getlist("file"):
        # print file
        filename = file.filename
        destination = "/".join([target,filename])
        app.logger.info('Accept incoming file: %s', filename)
        app.logger.info('Save it to: %s', destination)
        file.save(destination)

        s3 = boto3.client('s3')
        bucket_name = 'lemurndd'

        # Uploads the given file using a managed uploader, which will split up large
        # files automatically and upload parts in parallel.
        s3.upload_file(destination, bucket_name, filename)

        # Then grab the file from S3 bucket to show connection is established
        s3 = boto3.resource('s3')
        KEY = filename  # replace with your object key

        try:
            s3.Bucket(bucket_name).download_file(KEY, KEY)
            app.logger.info('Downloading file from S3...')
            # s = open(filename, 'r')
            # print s.read()
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == "404":
                app.logger.error('The object does not exist.')
            else:
                raise
                # s = open(destination, 'r')
                # print s.read()
    return render_template("complete.html",file_name = filename)

@app.route('/upload/<filename>')
def send_image(filename):
    return send_from_directory("text", filename)

@app.route('/display/<filename>')
def display_file(filename):
    target = os.path.join(APP_ROOT,'text')
    destination = "/".join([target, filename])
    s = open(destination, 'r')
    # print(s.read())
    return render_template("home.html", file_name=filename)

if __name__ == '__main__':
    handler = RotatingFileHandler('foo.log', maxBytes=10000, backupCount=1)
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.run(host='0.0.0.0')