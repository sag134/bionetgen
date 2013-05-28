# -*- coding: utf-8 -*-
"""
Created on Fri Mar  1 16:14:42 2013

@author: proto
"""

#!/usr/bin/env python
from scipy.misc import factorial,comb
from numpy import array
import matplotlib.pyplot as plt
import libsbml
import bnglWriter as writer
from optparse import OptionParser
import moleculeCreation as mc
import sys
import structures
from os import listdir
import numpy as np
import analyzeRDF
from util import logMess,NumericStringParser
import re
import pickle
log = {'species':[],'reactions':[]}
import signal

def handler(signum, frame):
    print "Forever is over!"
    raise Exception("end of time")

class SBML2BNGL:

    
    def __init__(self,model,useID=True):
        self.useID = useID
        self.model = model
        self.tags= {}
        self.speciesDictionary = {}
        self.getSpecies()
        self.reactionDictionary = {}
        

    def getRawSpecies(self, species):
        '''
        *species* is the element whose SBML information we will extract
        this method gets information directly
        from an SBML related to a particular species.
        It returns id,initialConcentration,(bool)isconstant and isboundary,
        and the compartment
        '''
        identifier = species.getId()
        name = species.getName()
        if name == '':
            name = identifier
        initialConcentration = species.getInitialConcentration()
        if initialConcentration ==0:
            initialConcentration = species.getInitialAmount()
        isConstant = species.getConstant()
        isBoundary = species.getBoundaryCondition()
        compartment = species.getCompartment()
        self.speciesDictionary[identifier] = standardizeName(name)
        returnID = identifier if self.useID else self.speciesDictionary[identifier]
        return (returnID,initialConcentration,isConstant,isBoundary,compartment,name)

   
    '''
    walks through a series of * nodes and removes the remainder reactant factors
    '''
    def getPrunnedTree(self,math,remainderPatterns):
        while (math.getCharacter() == '*' or math.getCharacter() == '/') and len(remainderPatterns) > 0:
            if libsbml.formulaToString(math.getLeftChild()) in remainderPatterns:
                remainderPatterns.remove(libsbml.formulaToString(math.getLeftChild()))
                math = math.getRightChild()
            elif libsbml.formulaToString(math.getRightChild()) in remainderPatterns:
                remainderPatterns.remove(libsbml.formulaToString(math.getRightChild()))
                math = math.getLeftChild()            
            else:
                if(math.getLeftChild().getCharacter()) == '*':
                    math.replaceChild(0,self.getPrunnedTree(math.getLeftChild(),remainderPatterns))
                if(math.getRightChild().getCharacter()) == '*':
                    math.replaceChild(math.getNumChildren() - 1,self.getPrunnedTree(math.getRightChild(),remainderPatterns))
                break
        return math

    def removeFactorFromMath(self,math,reactants,products):
        
            
        remainderPatterns = []
        highStoichoiMetryFactor = 1
        for x in reactants:
            highStoichoiMetryFactor  *= factorial(x[1])
            y = [i[1] for i in products if i[0] == x[0]]
            y = y[0] if len(y) > 0 else 0
            highStoichoiMetryFactor /= comb(x[1],y)
            for counter in range(0,int(x[1])):
                remainderPatterns.append(x[0])
        #for x in products:
        #    highStoichoiMetryFactor /= math.factorial(x[1])
        #remainderPatterns = [x[0] for x in reactants]
        math = self.getPrunnedTree(math,remainderPatterns)
        rateR = libsbml.formulaToString(math) 
        for element in remainderPatterns:
            rateR = 'if({0} >0,({1})/{0} ,0)'.format(element,rateR)
        if highStoichoiMetryFactor != 1:
            rateR = '{0}*{1}'.format(rateR,int(highStoichoiMetryFactor))

        return rateR,math.getNumChildren()
        
    def __getRawRules(self, reaction):
            
        if self.useID:
            reactant = [(reactant.getSpecies(),reactant.getStoichiometry()) for reactant in reaction.getListOfReactants() if reactant.getSpecies() != 'EmptySet']
            product = [(product.getSpecies(),product.getStoichiometry()) for product in reaction.getListOfProducts() if product.getSpecies() != 'EmptySet']
        else:
            reactant = [(self.speciesDictionary[reactant.getSpecies()],reactant.getStoichiometry()) for reactant in reaction.getListOfReactants()]
            product = [(self.speciesDictionary[product.getSpecies()],product.getStoichiometry()) for product in reaction.getListOfProducts()]
        kineticLaw = reaction.getKineticLaw()
        rReactant = [(x.getSpecies(),x.getStoichiometry()) for x in reaction.getListOfReactants() if x.getSpecies() != 'EmptySet']
        rProduct = [(x.getSpecies(),x.getStoichiometry()) for x in reaction.getListOfProducts() if x.getSpecies() != 'EmptySet']
        #rReactant = [reactant for reactant in reaction.getListOfReactants()]
        parameters = [(parameter.getId(),parameter.getValue()) for parameter in kineticLaw.getListOfParameters()]

        #TODO: For some reason creating a deepcopy of this screws everything up, even
        #though its what we should be doing
        math = kineticLaw.getMath()
        reversible = reaction.getReversible()
        
        #get a list of compartments so that we can remove them
        compartmentList  = []
        for compartment in (self.model.getListOfCompartments()):
            compartmentList.append(compartment.getId())
        
        #remove compartments from expression
        math = self.getPrunnedTree(math,compartmentList)
            
        if reversible:
            if math.getCharacter() == '-' and math.getNumChildren() > 1:
                rateL,nl = (self.removeFactorFromMath(math.getLeftChild().deepCopy(),rReactant,rProduct))
                rateR,nr = (self.removeFactorFromMath(math.getRightChild().deepCopy(),rProduct,rReactant))
            else:
                rateL,nl = self.removeFactorFromMath(math,rReactant,rProduct)
                rateL = "if({0} >= 0 ,{0},0)".format(rateL)
                rateR,nr = self.removeFactorFromMath(math,rReactant,rProduct)
                rateR = "if({0} < 0 ,-({0}),0)".format(rateR)
                nl,nr = 1,1
        else:
            rateL,nl =(self.removeFactorFromMath(math.deepCopy(),rReactant,rProduct))
            rateR,nr = '0','-1'
                
        if not self.useID:
            rateL = self.convertToName(rateL)
            rateR = self.convertToName(rateR)
        if reversible:
            pass
        
        return (reactant,product,parameters,[rateL,rateR],reversible,reaction.getId(),[nl,nr])
        
    def convertToName(self,rate):
        for element in sorted(self.speciesDictionary,key=len,reverse=True):
            if element in rate:
                rate = re.sub(r'(\W|^)({0})(\W|$)'.format(element),r'\1 {0} \3'.format(self.speciesDictionary[element]),rate)
            #rate = rate.replace(element,self.speciesDictionary[element])
        return rate

    def __getRawCompartments(self, compartment):
        '''
        Private method used by the getCompartments method 
        '''
        name = compartment.getId()
        size = compartment.getSize()
        return name,3,size
        
    def __getRawFunctions(self,function):
        math= function[1].getMath()
        name = function[1].getId()
        
        return name,libsbml.formulaToString(math)

    def getSBMLFunctions(self):
        functions = {}
        for function in enumerate(self.model.getListOfFunctionDefinitions()):
            functionInfo = self.__getRawFunctions(function)
            functions[functionInfo[0]] = (writer.bnglFunction(functionInfo[1],functionInfo[0],[],reactionDict=self.reactionDictionary))
        return functions
            
    def getCompartments(self):
        '''
        Returns an array of triples, where each triple is defined as
        (compartmentName,dimensions,size)
        '''
        compartments = []
        for _,compartment in enumerate(self.model.getListOfCompartments()):
            compartmentInfo = self.__getRawCompartments(compartment)
            name = 'cell' if compartmentInfo[0] == '' else compartmentInfo[0]
            compartments.append("%s  %d  %s" % (name,compartmentInfo[1],compartmentInfo[2]))
        return compartments

    def updateFunctionReference(self,reaction,updatedReferences):
        newRate = reaction[3]
        for reference in updatedReferences:
            newRate = re.sub(r'(\W|^)({0})(\W|$)'.format(reference),r'\1 {0} \3'.format(updatedReferences[reference]),newRate)
        return newRate
    
    def getReactions(self, translator=[],isCompartments=False,extraParameters={}):
        '''
        returns a triple containing the parameters,rules,functions
        '''
        rules = []
        parameters = []
        
        functions = []
        tester = NumericStringParser()
        
        functionTitle = 'functionRate'
        for index,reaction in enumerate(self.model.getListOfReactions()):
            parameterDict = {}
            rawRules =  self.__getRawRules(reaction)
            #newRate = self.updateFunctionReference(rawRules,extraParameters)
            if len(rawRules[2]) >0:
                for parameter in rawRules[2]:
                    parameters.append('r%d_%s %f' % (index+1,parameter[0],parameter[1]))
                    parameterDict[parameter[0]] = parameter[1]
            compartmentList = [['cell',1]]
            compartmentList.extend([[self.__getRawCompartments(x)[0],self.__getRawCompartments(x)[2]] for x in self.model.getListOfCompartments()])
            threshold = 0     
            if rawRules[6][0] > threshold:            
                functionName = '%s%d()' % (functionTitle,index)
            else:
                #append reactionNumbers to parameterNames
                finalString = str(rawRules[3][0])
                for parameter in parameterDict:
                    finalString = re.sub(r'(\W|^)({0})(\W|$)'.format(parameter),r'\1 {0} \3'.format('r{0}_{1}'.format(index+1,parameter)),finalString)
                functionName = finalString
            if 'delay' in rawRules[3][0]:
                logMess('ERROR','BNG cannot handle delay functions in function %s' % functionName)
            if rawRules[4]:
                if rawRules[6][0] > threshold:
                    functions.append(writer.bnglFunction(rawRules[3][0],functionName,rawRules[0],compartmentList,parameterDict,self.reactionDictionary))
                if rawRules[6][1] > threshold:
                    functionName2 = '%s%dm()' % (functionTitle,index)                
                    functions.append(writer.bnglFunction(rawRules[3][1],functionName2,rawRules[0],compartmentList,parameterDict,self.reactionDictionary))
                    self.reactionDictionary[rawRules[5]] = '({0} - {1})'.format(functionName, functionName2)                
                    functionName = '{0},{1}'.format(functionName,functionName2)
                else:
                    finalString = str(rawRules[3][1])
                    for parameter in parameterDict:
                        finalString = re.sub(r'(\W|^)({0})(\W|$)'.format(parameter),r'\1 {0} \3'.format('r{0}_{1}'.format(index+1,parameter)),finalString)
                    functionName = '{0},{1}'.format(functionName,finalString)
            else:
                if rawRules[6][0] > threshold:
                    functions.append(writer.bnglFunction(rawRules[3][0],functionName,rawRules[0],compartmentList,parameterDict,self.reactionDictionary))
                    self.reactionDictionary[rawRules[5]] = '{0}'.format(functionName)
            rules.append(writer.bnglReaction(rawRules[0],rawRules[1],functionName,self.tags,translator,isCompartments,rawRules[4]))
        return parameters, rules,functions

    def __getRawAssignmentRules(self,arule):
        variable =   arule.getVariable()
        rate = libsbml.formulaToString(arule.getMath())
        
        #try to separate into positive and negative sections
        if arule.getMath().getCharacter() == '-' and arule.getMath().getNumChildren() > 1 and not arule.isAssignment():
            rateL = libsbml.formulaToString(arule.getMath().getLeftChild())
            if(arule.getMath().getRightChild().getCharacter()) == '*':
                if libsbml.formulaToString(arule.getMath().getRightChild().getLeftChild()) == variable:
                    rateR = libsbml.formulaToString(arule.getMath().getRightChild().getRightChild())
                elif libsbml.formulaToString(arule.getMath().getRightChild().getRightChild()) == variable:
                    rateR = libsbml.formulaToString(arule.getMath().getRightChild().getLeftChild())
                else:
                    rateR = 'if({0} >0,({1})/{0} ,0)'.format(variable,libsbml.formulaToString(arule.getMath().getRightChild()))
            else:
                rateR = 'if({0} >0,({1})/{0} ,0)'.format(variable,libsbml.formulaToString((arule.getMath().getRightChild())))
        else:
            rateL = libsbml.formulaToString(arule.getMath())
            rateR = '0'
        if not self.useID:
            rateL = self.convertToName(rateL)
            rateR = self.convertToName(rateR)
            variable = self.convertToName(variable).strip()
        #print arule.isAssignment(),arule.isRate()
        return variable,[rateL,rateR],arule.isAssignment(),arule.isRate()
        
    def getAssignmentRules(self,paramRules,parameters,molecules):
        compartmentList = [['cell',1]]
        compartmentList.extend([[self.__getRawCompartments(x)[0],self.__getRawCompartments(x)[2]] for x in self.model.getListOfCompartments()])

        arules = []
        aParameters = {}
        zRules = paramRules
        removeParameters = []
        newSeedSpecies = []
        artificialReactions = []
        artificialObservables = {}
        for arule in self.model.getListOfRules():
            rawArule = self.__getRawAssignmentRules(arule)
            #newRule = rawArule[1].replace('+',',').strip()
            if rawArule[3] == True:
                rateLaw1 = rawArule[1][0]
                rateLaw2 = rawArule[1][1]
                arules.append(writer.bnglFunction(rateLaw1,'arRate{0}'.format(rawArule[0]),[],compartments=compartmentList,reactionDict=self.reactionDictionary))
                arules.append(writer.bnglFunction(rateLaw2,'armRate{0}'.format(rawArule[0]),[],compartments=compartmentList,reactionDict=self.reactionDictionary))
                artificialReactions.append(writer.bnglReaction([],[[rawArule[0],1]],'{0},{1}'.format('arRate{0}'.format(rawArule[0]),'armRate{0}'.format(rawArule[0])),self.tags,{},isCompartments=True,comment = '#rateLaw'))
                if rawArule[0] in paramRules:
                    removeParameters.append('{0} 0'.format(rawArule[0]))
                    zRules.remove(rawArule[0])
                else:
                    for element in parameters:
                        if re.search('^{0}\s'.format(rawArule[0]),element):
                            removeParameters.append(element)
                        
            elif rawArule[2] == True:
                artificialObservables[rawArule[0]] = writer.bnglFunction(rawArule[1][0],rawArule[0]+'()',[],compartments=compartmentList,reactionDict=self.reactionDictionary)
                if rawArule[0] in zRules:
                    zRules.remove(rawArule[0])
                #if rawArule[0] in paramRules:
                #    removeParameters.append('{0} 0'.format(rawArule[0]))
            
            else:
                        
                if rawArule[0] not in paramRules:
                    ruleName = 'ar' + rawArule[0]
                else:
                    ruleName = rawArule[0]
                    zRules.remove(rawArule[0])
                arules.append(writer.bnglFunction(rawArule[1][0],ruleName,[],compartments=compartmentList,reactionDict=self.reactionDictionary))
                aParameters[rawArule[0]] = 'ar' + rawArule[0]
            '''
            elif rawArule[2] == True:
                for parameter in parameters:
                    if re.search('^{0}\s'.format(rawArule[0]),parameter):
                        print '////',rawArule[0]
            '''

            #arules.append('%s = %s' %(rawArule[0],newRule))
        return aParameters,arules,zRules,artificialReactions,removeParameters,artificialObservables

    def getParameters(self):
        parameters = []
        zparam = []
        for parameter in self.model.getListOfParameters():
            parameterSpecs = (parameter.getId(),parameter.getValue(),parameter.getConstant())
            #reserved keywords
            if parameterSpecs[0] == 'e':
                parameterSpecs = ('are',parameterSpecs[1])
            if parameterSpecs[1] == 0:
                zparam.append(parameterSpecs[0])
            else:
                parameters.append('{0} {1}'.format(parameterSpecs[0], parameterSpecs[1]))

        #return ['%s %f' %(parameter.getId(),parameter.getValue()) for parameter in self.model.getListOfParameters() if parameter.getValue() != 0], [x.getId() for x in self.model.getListOfParameters() if x.getValue() == 0]
        return parameters,zparam

    def getSpecies(self,translator = {}):

        moleculesText  = []
        speciesText = []
        observablesText = []
        nullFlag = False
        names = []
        rawSpeciesName = translator.keys()
        for species in self.model.getListOfSpecies():
            
            rawSpecies = self.getRawSpecies(species)
            if (rawSpecies[4] != ''):
                self.tags[rawSpecies[0]] = '@%s' % (rawSpecies[4])
            if(rawSpecies[0] in translator):
                if rawSpecies[0] in rawSpeciesName:
                    rawSpeciesName.remove(rawSpecies[0])
                if translator[rawSpecies[0]].getSize()==1 and translator[rawSpecies[0]].molecules[0].name not in names:
                    names.append(translator[rawSpecies[0]].molecules[0].name)
                    moleculesText.append(translator[rawSpecies[0]].str2())
            else:
                moleculesText.append(rawSpecies[0] + '()')
            temp = '$' if rawSpecies[2] != 0 else ''
            tmp = translator[str(rawSpecies[0])] if rawSpecies[0] in translator \
                else rawSpecies[0] + '()'
            if rawSpecies[1]>=00:
                #tmp= translator[rawSpecies[0]].toString()
                #print translator[rawSpecies[0]].toString()
                tmp2 = temp
                if rawSpecies[0] in self.tags:
                    tmp2 = (self.tags[rawSpecies[0]])
                if rawSpecies[1] > 0:
                    speciesText.append('%s:%s%s %f' % (tmp2,temp,str(tmp),rawSpecies[1]))
            if rawSpecies[0] == 'e':
                modifiedName = 'are'
            else:
                modifiedName = rawSpecies[0]
            observablesText.append('Species %s %s #%s' % (modifiedName, tmp,rawSpecies[5]))
        sorted(rawSpeciesName,key=len)
        for species in rawSpeciesName:
            if translator[species].getSize()==1 and translator[species].molecules[0].name not in names:
                names.append(translator[species].molecules[0].name)
                moleculesText.append(translator[species].str2())
        #moleculesText.append('NullSpecies()')
        #speciesText.append('$NullSpecies() 1')
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
        
    def getModelAnnotation(self):
        modelAnnotation = []
        annotationXML = self.model.getAnnotation()
        lista = libsbml.CVTermList()
        libsbml.RDFAnnotationParser.parseRDFAnnotation(annotationXML,lista)
        if lista.getSize() == 0:
            modelAnnotations = []
        else:
            tempDict = {}
            for element in [2,3,4,5,6]:
                if lista.get(element) == None:
                    continue
                tempDict[lista.get(element).getBiologicalQualifierType()] = lista.get(element)
            if 3 in tempDict:
                modelAnnotation = tempDict[3].getResources()
            elif 0 in tempDict and ('GO' in tempDict[0].getResources().getValue(1) or 'kegg' in tempDict[0].getResources().getValue(1)):
                modelAnnotation = tempDict[0].getResources()
            elif 5 in tempDict:
                modelAnnotation = tempDict[5].getResources()
            else:
                if lista.get(3) != None and ('GO' in lista.get(3).getResources().getValue(0) or 'kegg' in lista.get(3).getResources().getValue(0)):
                    modelAnnotation = lista.get(3).getResources()
                    
                elif lista.get(4) != None and ('GO' in lista.get(4).getResources().getValue(0) or 'kegg' in lista.get(4).getResources().getValue(0)):
                    modelAnnotation = lista.get(4).getResources()
                elif lista.get(5) != None and ('GO' in lista.get(5).getResources().getValue(0) or 'kegg' in lista.get(5).getResources().getValue(0)):
                    modelAnnotation = lista.get(5).getResources()
                else:
                    if lista.get(3) != None and ('reactome' in lista.get(3).getResources().getValue(0)):
                        modelAnnotation = lista.get(3).getResources()
                        
                    elif lista.get(4) != None and ('reactome' in lista.get(4).getResources().getValue(0)):
                        modelAnnotation = lista.get(4).getResources()
                    elif lista.get(5) != None and ('reactome' in lista.get(5).getResources().getValue(0)):
                        modelAnnotation = lista.get(5).getResources()
                    elif lista.get(2) != None:
                        modelAnnotation = lista.get(2).getResources()
        return modelAnnotation
        
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

    def getStandardName(self,name):
        if name in self.speciesDictionary:
            return self.speciesDictionary[name]
        return name
        
def standardizeName(name):
    name2 = name
    
    
    name2 = name.replace("-","_")
    name2 = name2.replace("^","")
    name2 = name2.replace("'","")
    name2 = name2.replace("*","m")
    #name2 = name2.replace("#","m")
    name2 = name2.replace(" ","_")
    name2 = name2.replace(",","_")
    name2 = name2.replace('α','a')
    name2 = name2.replace('β','b')
    name2 = name2.replace('γ','g')
    name2 = name2.replace("(","")
    name2 = name2.replace(")","")
    name2 = name2.replace(" ","")
    name2 = name2.replace("+","")
    name2 = name2.replace("/","_")
    name2 = name2.replace(":","_")
    name2 = name2.replace(".","_")
    
    return name2
        


def identifyNamingConvention():
    '''
    extracts statistics from the code
    '''
    
    reader = libsbml.SBMLReader()
    jsonFiles = [ f for f in listdir('./reactionDefinitions') if f[-4:-1] == 'jso' and 'reactionDefinition' in f]
    translationLevel = []
    arrayMolecules = []
    rules = 0
    #go through all curated models in the biomodels database
    signal.signal(signal.SIGALRM, handler)
    for index in range(1,410):
        bestTranslator = {}
        
        nameStr = 'BIOMD0000000%03d' % (index)
        document = reader.readSBMLFromFile('XMLExamples/curated/' + nameStr + '.xml')
        parser = SBML2BNGL(document.getModel())
        database = structures.Databases()

        print nameStr + '.xml',
        naming = 'reactionDefinition0.json'
        bestUseID = True
        numberofMolecules = numberOfSpecies = 0
        #iterate through our naming conventions and selects that which
        #creates the most rulified elements in the translator
        for jsonFile in jsonFiles:
            for useID in [True,False]:
                    oldmaxi = numberOfSpecies
                    parser = SBML2BNGL(document.getModel(),useID)
                    database = structures.Databases()
                    signal.alarm(30)
                    try:
                        mc.transformMolecules(parser,database,'reactionDefinitions/' + jsonFile,None)
                    except:
                        print '--error',jsonFile,useID
                        continue
                    translator = database.translator                        
                    numberOfSpecies = max(numberOfSpecies,evaluation(len(parser.getSpecies()),database.translator))
                    if oldmaxi != numberOfSpecies:
                        naming = jsonFile
                        bestTranslator = translator
                        bestUseID = useID
                        _,rules,_ = parser.getReactions(translator)
                        numberofMolecules = len(translator)

        _,_,obs = parser.getSpecies()
        rdfAnnotations = analyzeRDF.getAnnotations(parser,'miriam')
        #go through the annotation list and assign which species
        #correspond to which uniprot number (if it exists)
        #similarly list the number of times each individual element appears
        analyzeRDF.getAnnotations(parser,'miriam')
        molecules = {}
        if naming[-6] != 0:
            for element in bestTranslator:
                if len(bestTranslator[element].molecules) == 1:
                    name = bestTranslator[element].molecules[0].name
                    for annotation in rdfAnnotations:
                        if name in rdfAnnotations[annotation]:
                            if name not in molecules:
                                molecules[name] = [0,[]]
                            if annotation not in molecules[name][1]:
                                molecules[name][1].extend(annotation)
                    
                    if  name not in molecules:
                        molecules[name] = [1,[]]
                    for rule in rules:
                        if name in rule:
                            molecules[name][0] += 1
        
       # _,rules,_ = parser.getReactions(bestTranslator)
       #for rule in rules:
        
        if len(obs) != 0:
            print index*1.0,(naming[-6]),numberOfSpecies*1.0/len(obs),numberofMolecules*1.0/len(obs),len(obs)*1.0,bestUseID
            
            arrayMolecule = [[x,molecules[x]] for x in molecules]
            arrayMolecules.append(arrayMolecule)
            translationLevel.append([nameStr+'.xml',(naming[-6]),numberOfSpecies*1.0/len(obs),numberofMolecules*1.0/len(obs),len(obs)*1.0,bestUseID])
        else:
            arrayMolecules.append([])
    with open('stats4.npy','wb') as f:
        pickle.dump(translationLevel,f)

        #np.save('stats3b.npy',np.array(arrayMolecules))

def processDatabase():
    reader = libsbml.SBMLReader()
    jsonFiles = [ f for f in listdir('./reactionDefinitions') if f[-4:-1] == 'jso']
    history = np.load('stats3.npy')
    index2 = 0
    for index in range(1,410):
        try:
            nameStr = 'BIOMD0000000%03d' % (index)
            document = reader.readSBMLFromFile('XMLExamples/curated/' + nameStr + '.xml')
            parser = SBML2BNGL(document.getModel())
            database = structures.Databases()

            print nameStr + '.xml'
            '''
            for jsonFile in jsonFiles:
                try:
                    #print jsonFile,
                    translator = m2c.transformMolecules(parser,database,'reactionDefinitions/' + jsonFile)
                    break
                except:
                    print 'ERROR',sys.exc_info()[0]
                    continue
                #translator = m2c.transformMolecules(parser,database,'reactionDefinition2.json')
            '''
            #translator = []
            while(history[index2][0] < index):
                    index2=1
            print history[index2][0],index
            if (history[index2][0]==index) and history[index2][1] != 0:
                print str( int(history[index2][1]))
                translator = m2c.transformMolecules(parser,database,'reactionDefinitions/reactionDefinition' + str( int(history[index2][1])) + '.json')            
            else:
                translator = {}
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
    nonStructuredElements = len([1 for x in translator if '()' in str(translator[x])])
    ruleElements = (len(translator) - nonStructuredElements)*1.0/originalElements
    return ruleElements


    #print rules
#14,18,56,19,49.87.88.107,109,111,120,139,140,145,151,153,171,175,182,202,205
#230,253,255,256,268,269,288,313,332,333,334,335,336,362,396,397,399,406


def selectReactionDefinitions(bioNumber):
    '''
    This method goes through the stats-biomodels database looking for the 
    best reactionDefinitions definition available
    '''
    with open('stats4.npy') as f:
        db = pickle.load(f)
    fileName = 'reactionDefinitions/reactionDefinition7.json'
    useID = True
    for element in db:    
        if element[0] == bioNumber and element[1] != '0':
            fileName = 'reactionDefinitions/reactionDefinition' + element[1] + '.json'
            useID = element[5]
        elif element[0] > bioNumber:
            break
    return fileName,useID


def resolveDependencies(dictionary,key,idx):
    counter = 0
    for element in dictionary[key]:
        if idx < 20:
            counter += resolveDependencies(dictionary,element,idx+1)
        else:
            counter += 1
    return len(dictionary[key]) + counter    
    
def validateReactionUsage(reactant,reactions):
    for element in reactions:
        if reactant in element:
            return element
    return None
def analyzeFile(bioNumber,reactionDefinitions,useID,outputFile,speciesEquivalence=None):
    
    useArtificialRules = False
    
    reader = libsbml.SBMLReader()
    document = reader.readSBMLFromFile(bioNumber)
    parser =SBML2BNGL(document.getModel(),useID)
    database = structures.Databases()
    #translator,log,rdf = m2c.transformMolecules(parser,database,reactionDefinitions,speciesEquivalence)
        
    #try:
    translator = mc.transformMolecules(parser,database,reactionDefinitions,speciesEquivalence)
    #translator={}    
    #except:
    #    print 'failure'
    #    return None,None,None,None
    
    #translator = {}
    param,zparam = parser.getParameters()
    molecules,species,observables = parser.getSpecies(translator)
    compartments = parser.getCompartments()
    functions = []
    idxArray = []
    param3,rules,tfunc = parser.getReactions(translator,len(compartments)>1)
    functions.extend(tfunc)
    aParameters,aRules,nonzparam,artificialRules,removeParams,artificialObservables = parser.getAssignmentRules(zparam,param,molecules)
    for element in nonzparam:
        param.append('{0} 0'.format(element))

    param = [x for x in param if x not in removeParams]
    tags = '@{0}'.format(compartments[0].split(' ')[0]) if len(compartments) == 1 else '@cell'
    molecules.extend([x.split(' ')[0] for x in removeParams])
    if len(molecules) == 0:
        compartments = []
    observables.extend('Species {0} {0}'.format(x.split(' ')[0]) for x in removeParams)
    for x in removeParams:
        species.append(x.split(' ')[0] + tags + ' ' + x.split(' ')[1])
    ##Comment out those parameters that are defined with assignment rules
    ##TODO: I think this is correct, but it may need to be checked
    for idx,parameter in enumerate(param):
        for key in artificialObservables:
            if re.search('^{0}\s'.format(key),parameter)!= None:
                idxArray.append(idx)
    
    for element in idxArray:
        param[element] = '#' + param[element]
    for key in artificialObservables:
        flag = -1
        for idx,observable in enumerate(observables):
            if 'Species {0} {0}()'.format(key) in observable:
                flag = idx
        if flag != -1:
            observables.pop(flag)
        functions.append(artificialObservables[key])
        flag = -1
        if '{0}()'.format(key) in molecules:
            flag = molecules.index('{0}()'.format(key))
        
        if flag != -1:
            result =validateReactionUsage(molecules[flag],rules)
            if result != None:
                logMess('ERROR','Pseudo observable {0} in reaction {1}'.format(molecules[flag],result))
            molecules.pop(flag)
            
        flag = -1
        for idx,specie in enumerate(species):
            if ':{0}('.format(key) in specie:
                flag = idx
        if flag != -1:
            species[flag] = '#' + species[flag]
    
    functions.extend(aRules)

    sbmlfunctions = parser.getSBMLFunctions()
    for interation in range(0,3):
        for sbml2 in sbmlfunctions:
            for sbml in sbmlfunctions:
                if sbml == sbml2:
                    continue
                if sbml in sbmlfunctions[sbml2]:
                    sbmlfunctions[sbml2] = writer.extendFunction(sbmlfunctions[sbml2],sbml,sbmlfunctions[sbml])
    
    for idx in range(0,len(functions)):
        for sbml in sbmlfunctions:
            if sbml in functions[idx]:
                functions[idx] = writer.extendFunction(functions[idx],sbml,sbmlfunctions[sbml])
        functions[idx] =re.sub(r'(\W|^)(time)(\W|$)',r'\1time()\3',functions[idx])
        functions[idx] =re.sub(r'(\W|^)(Time)(\W|$)',r'\1time()\3',functions[idx])
        functions[idx] =re.sub(r'(\W|^)(t)(\W|$)',r'\1time()\3',functions[idx])
    
    #functions.extend(sbmlfunctions)
    dependencies2 = {}
    for idx in range(0,len(functions)):
        dependencies2[functions[idx].split(' = ')[0].split('(')[0].strip()] = []
        for key in artificialObservables:
            oldfunc = functions[idx]
            functions[idx] = (re.sub(r'(\W|^)({0})([^\w(]|$)'.format(key),r'\1\2()\3',functions[idx]))
            if oldfunc != functions[idx]:
                dependencies2[functions[idx].split(' = ')[0].split('(')[0]].append(key)
        for element in sbmlfunctions:
            oldfunc = functions[idx]
            key = element.split(' = ')[0].split('(')[0]
            if re.search('(\W|^){0}(\W|$)'.format(key),functions[idx].split(' = ')[1]) != None:
                dependencies2[functions[idx].split(' = ')[0].split('(')[0]].append(key)
        for element in tfunc:
            key = element.split(' = ')[0].split('(')[0]
            if key in functions[idx].split(' = ')[1]:
                dependencies2[functions[idx].split( ' = ')[0].split('(')[0]].append(key)
    '''           
    for counter in range(0,3):
        for element in dependencies2:
            if len(dependencies2[element]) > counter:
                dependencies2[element].extend(dependencies2[dependencies2[element][counter]])
    '''
    fd = []
    for function in functions:
        fd.append([function,resolveDependencies(dependencies2,function.split(' = ' )[0].split('(')[0],0)])
    fd = sorted(fd,key= lambda rule:rule[1])
    functions = [x[0] for x in fd]
    #functions.extend(aRules)
    if len(compartments) > 1 and 'cell 3 1.0' not in compartments:
        compartments.append('cell 3 1.0')
    #sbml always has the 'cell' default compartment, even when it
    #doesn't declare it
    elif len(compartments) == 0 and len(molecules) != 0:
        compartments.append('cell 3 1.0')
    
    
    if len(artificialRules) + len(rules) == 0:
        logMess('ERROR','The file contains no reactions')
    if useArtificialRules or len(rules) == 0:
        rules =['#{0}'.format(x) for x in rules]
        evaluate =  evaluation(len(observables),translator)

        artificialRules.extend(rules)
        writer.finalText(param,molecules,species,observables,artificialRules,functions,compartments,outputFile)

    else:
        artificialRules =['#{0}'.format(x) for x in artificialRules]
        evaluate =  evaluation(len(observables),translator)

        rules.extend(artificialRules)
        
        writer.finalText(param+param3,molecules,species,observables,rules,functions,compartments,outputFile)
    print outputFile
    
    #store a logfile
    '''
    if len(logMess.log) > 0:
        with open(outputFile + '.log', 'w') as f:
            for element in logMess.log:
                f.write(element + '\n')
    '''

    #rate of each classified rule
    classificationDict = {}
    return len(rules),evaluate,len(molecules)*1.0/len(observables),len(compartments)
    
    '''
    if translator != {}:
        for element in database.classifications:
            if element not in classificationDict:
                classificationDict[element] = 0.0
            classificationDict[element] += 1.0/len(database.classifications)
        return len(rules), evaluate,parser.getModelAnnotation(),classificationDict
    '''
    #return None,None,None,None

def processFile(translator,parser,outputFile):
    param2 = parser.getParameters()
    molecules,species,observables = parser.getSpecies(translator)
    compartments = parser.getCompartments()
    param,rules,functions = parser.getReactions(translator,True)
    param += param2
    writer.finalText(param,molecules,species,observables,rules,functions,compartments,outputFile)

   
def BNGL2XML():
    pass

def getAnnotations(annotation):
    annotationDictionary = []
    if annotation ==[] or annotation ==None:
        return []
    for index in range(0,annotation.getNumAttributes()):
        annotationDictionary.append(annotation.getValue(index))
    return annotationDictionary



def main():
    jsonFiles = [ f for f in listdir('./reactionDefinitions') if f[-4:-1] == 'jso']
    jsonFiles.sort()
    parser = OptionParser()
    rulesLength = []
    evaluation = []
    evaluation2 = []
    compartmentLength = []
    parser.add_option("-i","--input",dest="input",
        default='XMLExamples/curated/BIOMD0000000272.xml',type="string",
        help="The input SBML file in xml format. Default = 'input.xml'",metavar="FILE")
    parser.add_option("-o","--output",dest="output",
        default='output.bngl',type="string",    
        help="the output file where we will store our matrix. Default = output.bngl",metavar="FILE")

    (options, _) = parser.parse_args()
    #144
    rdfArray = []
    classificationArray = []
    #18,32,87,88,91,109,253,255,268,338,330
    #normal:51,353
    #cycles 18,108,109,255,268,392
    for bioNumber in [19]:
        #if bioNumber in [18,51,353,108,109,255,268,392]:
        #    continue
    #bioNumber = 175
        logMess.log = []
        logMess.counter = -1
        reactionDefinitions,useID = selectReactionDefinitions('BIOMD%010i.xml' %bioNumber)
        print reactionDefinitions,useID
        reactionDefinitions = 'reactionDefinitions/reactionDefinition7.json'
        spEquivalence = 'reactionDefinitions/speciesEquivalence19.json'
        #spEquivalence = None
        #reactionDefinitions = 'reactionDefinitions/reactionDefinition8.json'
        
        rlength,reval,reval2,clength = analyzeFile('XMLExamples/curated/BIOMD%010i.xml' % bioNumber,reactionDefinitions,False,'complex/output' + str(bioNumber) + '.bngl',speciesEquivalence=spEquivalence)
               
        #rdfArray.append(getAnnotations(rdf))
        
        if rlength != None:        
            rulesLength.append(rlength)
            evaluation.append(reval)
            evaluation2.append(reval2)
            compartmentLength.append(clength)
        else:
            rulesLength.append(-1)
            evaluation.append(0)
            evaluation2.append(0)
            compartmentLength.append(0)
            #classificationArray.append({})
    #print evaluation
    #print evaluation2
    #sortedCurated = [i for i in enumerate(evaluation), key=lambda x:x[1]]
    with open('sortedC.dump','wb') as f:
        pickle.dump(rulesLength,f)
        pickle.dump(evaluation,f)
        pickle.dump(evaluation2,f)   
    #with open('annotations.dump','wb') as f:
    #    pickle.dump(rdfArray,f)
    #with open('classificationDict.dump','wb') as f:
    #    pickle.dump(classificationArray,f)
    plt.hist(rulesLength,bins=[10,30,50,70,90,110,140,180,250,400])
    plt.xlabel('Number of reactions',fontsize=18)
    plt.savefig('lengthDistro.png')
    plt.clf()
    plt.hist(evaluation,bins =[0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0])
    plt.xlabel('Atomization Degree',fontsize=18)    
    plt.savefig('ruleifyDistro.png')
    plt.clf()
    plt.hist(evaluation2,bins =[0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0])
    plt.xlabel('Atomization Degree',fontsize=18)    
    plt.savefig('ruleifyDistro2.png')
    plt.clf()
    ev = []
    idx = 1
    for x,y,z in zip(rulesLength,evaluation,compartmentLength):
        
        if idx in [18,51,353,108,109,255,268,392]:
            idx+=1

        if x < 15 and y > 0.7 and z>1:
            print '---',idx,x,y
        idx+=1
    #plt.hist(ev,bins =[0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0])
    #plt.xlabel('Atomization Degree',fontsize=18)    
    #plt.savefig('ruleifyDistro3.png')
            
            
if __name__ == "__main__":
    #identifyNamingConvention()
    #processDatabase()
    main()
#todo: some of the assignmentRules defined must be used instead of parameters. remove from the paraemter
#definitions those that are defined as 0'
#2:figure out which assignment rules are being used in reactions. Done before the substitution for id;s
#http://nullege.com/codes/show/src@s@e@semanticsbml-HEAD@semanticSBML@annotate.py
#http://wiki.geneontology.org/index.php/Example_Queries#Find_terms_by_GO_ID
#http://www.geneontology.org/GO.database.shtml  