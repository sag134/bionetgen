#!/usr/bin/env python

import libsbml
import bnglWriter as writer
from optparse import OptionParser
import molecules2complexes as m2c
import sys
import structures
from os import listdir
import re
import numpy as np

log = {'species':[],'reactions':[]}
class SBML2BNGL:

    
    def __init__(self,model):
        self.model = model
        self.tags= {}
        
        
    def getRawSpecies(self, species):
        '''
        *species* is the element whose SBML information we will extract
        this method gets information directly
        from an SBML related to a particular species.
        It returns id,initialConcentration,(bool)isconstant and isboundary,
        and the compartment
        '''
        id = species.getId()
        initialConcentration = species.getInitialConcentration()
        isConstant = species.getConstant()
        isBoundary = species.getBoundaryCondition()
        compartment = species.getCompartment()
        
        return (id,initialConcentration,isConstant,isBoundary,compartment)
        
    def __getRawRules(self, reaction):
        reactant = [(reactant.getSpecies(),reactant.getStoichiometry()) for reactant in reaction.getListOfReactants()]
        product = [(product.getSpecies(),product.getStoichiometry()) for product in reaction.getListOfProducts()]
        kineticLaw = reaction.getKineticLaw()
        parameters = [(parameter.getId(),parameter.getValue()) for parameter in kineticLaw.getListOfParameters()]
        math = kineticLaw.getMath()
        rate = libsbml.formulaToString(math)
        for element in reactant:
            rate = rate.replace('* %s' % element[0],'',1)
        return (reactant,product,parameters,rate)
        
    def __getRawCompartments(self, compartment):
        name = compartment.getName()
        size = compartment.getSize()
        return name,3,size
    
    def getCompartments(self):
        compartments = []
        for index,compartment in enumerate(self.model.getListOfCompartments()):
            compartmentInfo = self.__getRawCompartments(compartment)
            name = 'cell' if compartmentInfo[0] == '' else compartmentInfo[0]
            compartments.append("%s  %d  %s" % (name,compartmentInfo[1],compartmentInfo[2]))
        return compartments
        
            
    def getReactions(self, translator=[]):
        rules = []
        parameters = []
        functions = []
        functionTitle = 'functionRate'
        for index,reaction in enumerate(self.model.getListOfReactions()):
            rawRules =  self.__getRawRules(reaction)
            #print rawRules
            functionName = '%s%d()' % (functionTitle,index)
            rules.append(writer.bnglReaction(rawRules[0],rawRules[1],functionName,self.tags,translator))
            
            if len(rawRules[2]) >0:
                parameters.append('%s %f' % (rawRules[2][0][0],rawRules[2][0][1]))
            compartmentList = ['cell']
            compartmentList.extend([x.getName() for x in self.model.getListOfCompartments() if x.getName() is not ''])
            functions.append(writer.bnglFunction(rawRules[3],functionName,compartmentList) )
        return parameters, rules,functions
            
    def getParameters(self):
        return ['%s %f' %(parameter.getId(),parameter.getValue()) for parameter in self.model.getListOfParameters()]
    
        
    def getSpecies(self,translator = {}):
    
        moleculesText  = []
        speciesText = [] 
        observablesText = []
        
        for species in self.model.getListOfSpecies():
            rawSpecies = self.getRawSpecies(species)
            
            if (rawSpecies[4] != ''):   
                self.tags[rawSpecies[0]] = '@%s:' % (rawSpecies[4])
            if(rawSpecies[0] in translator):
                if translator[rawSpecies[0]].getSize()==1:
                    moleculesText.append(translator[rawSpecies[0]].toString())
            else:
                moleculesText.append(rawSpecies[0] + '()')
            temp = '$' if rawSpecies[2] != 0 else ''
            tmp = translator[rawSpecies[0]].toString() if rawSpecies[0] in translator \
                else rawSpecies[0] + '()'
            if rawSpecies[1]>0:
                #tmp= translator[rawSpecies[0]].toString()
                #print translator[rawSpecies[0]].toString()
                speciesText.append(temp + '%s %f' % (tmp,rawSpecies[1]))
            observablesText.append('Species %s %s' % (rawSpecies[0], tmp))
        return moleculesText,speciesText,observablesText
    
    def getSpeciesAnnotation(self):
        speciesAnnotation = {}
        
        for species in self.model.getListOfSpecies():
            rawSpecies = self.getRawSpecies(species)
            annotationXML = species.getAnnotation()
            lista = libsbml.CVTermList()
            libsbml.RDFAnnotationParser.parseRDFAnnotation(annotationXML,lista)
            if lista.getSize() == 0:
                speciesAnnotation[rawSpecies[0]] =  None
            else:
                speciesAnnotation[rawSpecies[0]] = lista.get(0).getResources()
        return speciesAnnotation
        
    def getSpeciesInfo(self,name):
        return self.getRawSpecies(self.model.getSpecies(name))
        
    def writeLog(self,translator):
        rawSpecies = [self.getRawSpecies(x) for x in self.model.getListOfSpecies()]
        log['species'].extend([x[0] for x in rawSpecies if x[0] not in translator])
        logString = ''
        #species stuff
        if(len(log['species']) > 0):
            logString += "Species we couldn't recognize:\n"
            for element in log['species']:
                logString += '\t%s\n' % element
        if(len(log['reactions'])>0):
            logString += "Reactions we couldn't infer more about due to insufficient information:"
            for element in log['reactions']:
                logString += '\t%s + %s -> %s\n' % (element[0][0],element[0][1],element[1])
        return logString


def identifyNamingConvetion():
    reader = libsbml.SBMLReader()
    jsonFiles = [ f for f in listdir('./reactionDefinitions') if f[-4:-1] == 'jso']
    translationLevel = []
    maxi = 0
    for index in range(1,410):
        try:
            nameStr = 'BIOMD0000000%03d' % (index)
            document = reader.readSBMLFromFile('XMLExamples/curated/' + nameStr + '.xml')
            parser = SBML2BNGL(document.getModel())
            database = structures.Databases()
            
            print nameStr + '.xml',
            maxi = 0
            for jsonFile in jsonFiles:
                try:
                    parser = SBML2BNGL(document.getModel())
                    database = structures.Databases()
                    translator = m2c.transformMolecules(parser,database,'reactionDefinitions/' + jsonFile)
                    maxi = max(maxi,evaluation(len(parser.getSpecies()),translator))
                except:
                    print 'ERROR',sys.exc_info()[0]  
                    continue
                #translator = m2c.transformMolecules(parser,database,'reactionDefinition2.json')
            #print len(parser.getSpecies()),len(translator),
            #evaluation(len(parser.getSpecies()),translator)
            
            #translator = {}
            _,_,obs = parser.getSpecies()
            print maxi,maxi*1.0/len(obs)
            translationLevel.append(maxi*1.0/len(obs))
        except:
            print 'ERROR',sys.exc_info()[0] 
            continue
        np.save('stats2.npy',translationLevel)
                
def processDatabase():
    reader = libsbml.SBMLReader()
    jsonFiles = [ f for f in listdir('./reactionDefinitions') if f[-4:-1] == 'jso']
    for index in range(1,410):
        try:
            nameStr = 'BIOMD0000000%03d' % (index)
            document = reader.readSBMLFromFile('XMLExamples/curated/' + nameStr + '.xml')
            parser = SBML2BNGL(document.getModel())
            database = structures.Databases()
            
            print nameStr + '.xml'
                        
            for jsonFile in jsonFiles:
                try:
                    #print jsonFile,           
                    translator = m2c.transformMolecules(parser,database,'reactionDefinitions/' + jsonFile)
                    break
                except:
                    print 'ERROR',sys.exc_info()[0]  
                    continue
                #translator = m2c.transformMolecules(parser,database,'reactionDefinition2.json')
            #print len(parser.getSpecies()),len(translator),
            evaluation(len(parser.getSpecies()),translator)
            
            #translator = {}
            param2 = parser.getParameters()
            molecules,species,observables = parser.getSpecies(translator)
            #print molecules,species,observables
            print 'translated: {0}/{1}'.format(len(translator),len(observables)),
            print evaluation(len(observables),translator)
            param,rules,functions = parser.getReactions(translator)
            compartments = parser.getCompartments()
            param += param2
            writer.finalText(param,molecules,species,observables,rules,functions,compartments,'output/' + nameStr + '.bngl')
            with open('output/' + nameStr + '.log', 'w') as f:
                f.write(parser.writeLog(translator))
        except:
            print 'ERROR',sys.exc_info()[0] 
            continue
            
def evaluation(numMolecules,translator):
    originalElements = (numMolecules)
    ruleElements = len([str(translator[x]) for x in translator if '.' not in str(translator[x])])
    return ruleElements

           
    #print rules
#14,18,56,19,49.87.88.107,109,111,120,139,140,145,151,153,171,175,182,202,205
#230,253,255,256,268,269,288,313,332,333,334,335,336,362,396,397,399,406
def main():
    jsonFiles = [ f for f in listdir('./reactionDefinitions') if f[-4:-1] == 'jso']
    jsonFiles.sort()
    parser = OptionParser()
    parser.add_option("-i","--input",dest="input",
        default='XMLExamples/curated/BIOMD0000000272.xml',type="string",
        help="The input SBML file in xml format. Default = 'input.xml'",metavar="FILE")
    parser.add_option("-o","--output",dest="output",
        default='output.bngl',type="string",
        help="the output file where we will store our matrix. Default = output.bngl",metavar="FILE")
          
    (options, args) = parser.parse_args()
    reader = libsbml.SBMLReader()
    #document = reader.readSBMLFromFile(options.input)
    #document = reader.readSBMLFromFile('XMLExamples/curated/BIOMD0000000011.xml')
    document = reader.readSBMLFromFile('XMLExamples/curated/BIOMD0000000048.xml')
    #document = reader.readSBMLFromFile('XMLExamples/curated/BIOMD0000000188.xml')
    #document = reader.readSBMLFromFile('XMLExamples/curated/BIOMD0000000018.xml')
    #document = reader.readSBMLFromFile('XMLExamples/curated/BIOMD0000000009.xml')
    #document = reader.readSBMLFromFile('XMLExamples/curated/BIOMD0000000270.xml')
    #document = reader.readSBMLFromFile('XMLExamples/curated/BIOMD0000000272.xml')
    #document = reader.readSBMLFromFile('XMLExamples/simple4.xml')
    parser =SBML2BNGL(document.getModel())
    #rawDatabase = {('EpoR',):([('ra',),('U',),('I',)],),('SAv',):([('l',)],)}
    database = structures.Databases()
    #rawDatabase = {}    
    #rawDatabase = {('S1',):([("a",),("b",),("c",)],),("S2",):([("r",),("k")],),
    #              ('S3',):([("l",)],),('S4',):([('t',)],)}  
    translator = m2c.transformMolecules(parser,database,'reactionDefinitions/reactionDefinition4.json')            
    #translator= {}
    #print {x:str(translator[x]) for x in translator}
    print evaluation(len(parser.getSpecies()[0]),translator)
    param2 = parser.getParameters()
    
    
    molecules,species,observables = parser.getSpecies(translator)
    #print species
    #print molecules,species,observables
    compartments = parser.getCompartments()
    param,rules,functions = parser.getReactions(translator)
    
    
    
    
    param += param2
    #print rules
         
    writer.finalText(param,molecules,species,observables,rules,functions,compartments,options.output)

    #print parser.writeLog(translator)
    #print database.labelDictionary
    #print rawDatabase
    
if __name__ == "__main__":
    #identifyNamingConvetion()
    #processDatabase()
    main()
